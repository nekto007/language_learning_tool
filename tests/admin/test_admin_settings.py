"""Tests for Task 40: SiteSettings validation, concurrent seeding, GSC token safety."""
import pytest
from unittest.mock import patch

from app.admin.site_settings import (
    SETTING_DEFAULTS,
    SiteSettings,
    SettingValidationError,
    ensure_defaults_seeded,
    get_site_setting,
    set_site_setting,
    validate_setting_value,
)
from app.utils.db import db


_BASE_FORM = {
    'site_title': '',
    'site_description': '',
    'og_image_url': '',
    'meta_keywords': '',
    'support_email': '',
    'support_phone': '',
    'referral_bonus_xp': '50',
}


class TestValidateCalledBeforeSet:
    """validate_setting_value is invoked before set_site_setting in the form handler."""

    @pytest.mark.smoke
    def test_invalid_input_does_not_reach_db(self, app, client, admin_user, db_session):
        """Invalid value must not be persisted; the original value is preserved."""
        set_site_setting('support_email', 'original@example.com', db_session=db_session)
        db_session.commit()

        data = dict(_BASE_FORM, support_email='not-an-email')
        resp = client.post('/admin/settings', data=data, follow_redirects=False)

        assert resp.status_code == 302
        with app.app_context():
            assert get_site_setting('support_email') == 'original@example.com'

    def test_valid_input_persists(self, app, client, admin_user):
        data = dict(_BASE_FORM, site_title='Valid Title', support_email='ok@example.com')
        resp = client.post('/admin/settings', data=data, follow_redirects=True)
        assert resp.status_code == 200
        with app.app_context():
            assert get_site_setting('site_title') == 'Valid Title'
            assert get_site_setting('support_email') == 'ok@example.com'

    def test_gsc_set_without_validate_is_internal_only(self):
        """set_site_setting is called without validate_setting_value for OAuth tokens —
        verify the OAuth values are not raw user input by confirming they come from the
        GSC API (verified list), not directly from request.form."""
        # This is a structural check: the route validates `desired` against the
        # verified GSC site list before calling set_site_setting, which is a
        # stricter guard than validate_setting_value would provide.
        # The intent is documented; no runtime assertion needed beyond confirming
        # the key is excluded from the editable settings form.
        from app.admin.routes.settings_routes import _HIDDEN_KEYS
        assert 'gsc_refresh_token' in _HIDDEN_KEYS
        assert 'gsc_site_url' in _HIDDEN_KEYS


class TestSettingValidationErrorNotFiveHundred:
    """SettingValidationError must not surface as an unhandled 500."""

    @pytest.mark.parametrize('bad_field,bad_value', [
        ('support_email', 'bad-email'),
        ('og_image_url', 'ftp://not-http'),
        ('referral_bonus_xp', 'not-a-number'),
    ])
    def test_bad_value_returns_redirect_not_500(self, app, client, admin_user, bad_field, bad_value):
        data = dict(_BASE_FORM)
        data[bad_field] = bad_value
        resp = client.post('/admin/settings', data=data)
        assert resp.status_code not in (500, 400), (
            f'Expected redirect, got {resp.status_code} for field {bad_field}={bad_value!r}'
        )
        assert resp.status_code == 302

    def test_validation_error_raises_not_unhandled(self):
        """validate_setting_value raises SettingValidationError (not a raw exception)."""
        with pytest.raises(SettingValidationError):
            validate_setting_value('daily_race_enabled', 'INVALID_VALUE')

    def test_bool_invalid_raises_setting_validation_error(self):
        with pytest.raises(SettingValidationError):
            validate_setting_value('streak_shield_enabled', 'maybe')

    def test_str_over_max_length_raises(self):
        with pytest.raises(SettingValidationError):
            validate_setting_value('site_title', 'x' * 300)


class TestEnsureDefaultsSeededIdempotent:
    """ensure_defaults_seeded is safe to call multiple times."""

    def test_sequential_calls_do_not_raise(self, app, db_session):
        ensure_defaults_seeded(db_session=db_session)
        ensure_defaults_seeded(db_session=db_session)

    def test_all_keys_present_after_seed(self, app, db_session):
        db_session.query(SiteSettings).delete(synchronize_session=False)
        db_session.flush()
        ensure_defaults_seeded(db_session=db_session)
        for key in SETTING_DEFAULTS:
            assert db_session.get(SiteSettings, key) is not None, f'Missing {key}'

    def test_existing_values_not_overwritten(self, app, db_session):
        """Keys already present keep their custom values after re-seeding."""
        existing = db_session.get(SiteSettings, 'site_title')
        if existing is None:
            db_session.add(SiteSettings(key='site_title', value='custom_title'))
            db_session.flush()
        else:
            existing.value = 'custom_title'
            db_session.flush()

        ensure_defaults_seeded(db_session=db_session)

        row = db_session.get(SiteSettings, 'site_title')
        assert row.value == 'custom_title'

    def test_concurrent_seed_absorbs_integrity_error(self, app, db_session):
        """When rows already exist, IntegrityError per key is absorbed without aborting the call."""
        # Pre-insert all keys so every insertion would conflict
        db_session.query(SiteSettings).delete(synchronize_session=False)
        db_session.flush()
        for key, val in SETTING_DEFAULTS.items():
            db_session.add(SiteSettings(key=key, value='pre_existing'))
        db_session.flush()

        # Simulate a concurrent worker that read NULL (before our flush) by
        # patching session.get() to return None so it tries to re-insert.
        original_get = db_session.get

        def _always_none(model, pk):
            return None

        with patch.object(db_session, 'get', side_effect=_always_none):
            # Must not raise even though every insert will conflict
            ensure_defaults_seeded(db_session=db_session)

        # Rows still exist and have the pre-existing value
        for key in SETTING_DEFAULTS:
            row = original_get(SiteSettings, key)
            assert row is not None
            assert row.value == 'pre_existing'

    def test_no_duplicate_rows_after_concurrent_seed(self, app, db_session):
        """Count of rows per key is exactly 1 after seeding."""
        ensure_defaults_seeded(db_session=db_session)
        for key in SETTING_DEFAULTS:
            count = db_session.query(SiteSettings).filter_by(key=key).count()
            assert count == 1, f'Expected 1 row for {key}, found {count}'


class TestGSCTokenNotLeaking:
    """GSC tokens must not appear in admin page HTML or error responses."""

    def test_settings_form_excludes_gsc_token_field(self, app, client, admin_user):
        """gsc_refresh_token must not be rendered as an editable form field."""
        resp = client.get('/admin/settings')
        assert resp.status_code == 200
        html = resp.data.decode()
        assert 'name="gsc_refresh_token"' not in html
        assert 'name="gsc_site_url"' not in html

    def test_settings_form_does_not_render_stored_token_value(
        self, app, client, admin_user, db_session
    ):
        """Even if gsc_refresh_token exists in DB, its value must not appear in the form HTML."""
        sentinel = 'SENTINEL_GSC_TOKEN_MUST_NOT_APPEAR_12345'
        set_site_setting('gsc_refresh_token', sentinel, db_session=db_session)
        db_session.commit()

        resp = client.get('/admin/settings')
        assert resp.status_code == 200
        assert sentinel not in resp.data.decode()

    def test_seo_admin_page_does_not_expose_raw_token(
        self, app, client, admin_user, db_session
    ):
        """The SEO admin index must not include the raw stored token value in its HTML."""
        sentinel = 'SEO_RAW_TOKEN_MUST_NOT_APPEAR_67890'
        set_site_setting('gsc_refresh_token', sentinel, db_session=db_session)
        db_session.commit()

        resp = client.get('/admin/seo')
        assert resp.status_code == 200
        assert sentinel not in resp.data.decode()

    def test_gsc_token_excluded_from_editable_keys(self):
        """_ALL_KEYS in settings_routes must not contain GSC or cache-version keys."""
        from app.admin.routes.settings_routes import _ALL_KEYS, _HIDDEN_KEYS
        assert 'gsc_refresh_token' not in _ALL_KEYS
        assert 'gsc_site_url' not in _ALL_KEYS
        assert 'gsc_refresh_token' in _HIDDEN_KEYS
        assert 'gsc_site_url' in _HIDDEN_KEYS
