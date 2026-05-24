"""Tests for SiteSettings model and get/set helpers."""
import pytest

from app.admin.site_settings import (
    SiteSettings,
    SETTING_DEFAULTS,
    SETTING_META,
    SettingValidationError,
    get_site_setting,
    set_site_setting,
    ensure_defaults_seeded,
    validate_setting_value,
)
from app.utils.db import db


class TestGetSiteSetting:
    """Tests for get_site_setting()."""

    @pytest.mark.smoke
    def test_returns_default_when_key_missing(self, app, db_session):
        """get_site_setting returns the provided default for an unknown key."""
        result = get_site_setting('nonexistent_key_xyz', default='my_default', db_session=db_session)
        assert result == 'my_default'

    def test_returns_stored_value(self, app, db_session):
        """get_site_setting returns the DB value when the key exists."""
        row = SiteSettings(key='test_key_read', value='stored_value')
        db_session.add(row)
        db_session.flush()

        result = get_site_setting('test_key_read', default='fallback', db_session=db_session)
        assert result == 'stored_value'

    def test_returns_default_without_writing(self, app, db_session):
        """get_site_setting is read-only: missing row → return default, no DB write."""
        existing = db_session.get(SiteSettings, 'support_email')
        if existing is not None:
            db_session.delete(existing)
            db_session.flush()

        result = get_site_setting('support_email', db_session=db_session)
        assert result == SETTING_DEFAULTS['support_email']

        # No row should be created by a read-only call
        assert db_session.get(SiteSettings, 'support_email') is None

    def test_returns_none_default_when_no_default_arg(self, app, db_session):
        """get_site_setting with no default arg returns SETTING_DEFAULTS value or None."""
        # A key not in SETTING_DEFAULTS with no default arg
        result = get_site_setting('totally_unknown_key_abc', db_session=db_session)
        assert result is None


class TestSetSiteSetting:
    """Tests for set_site_setting()."""

    @pytest.mark.smoke
    def test_creates_new_row(self, app, db_session):
        """set_site_setting creates a row when key does not exist."""
        set_site_setting('new_test_key', 'hello', db_session=db_session)
        row = db_session.get(SiteSettings, 'new_test_key')
        assert row is not None
        assert row.value == 'hello'

    def test_updates_existing_row(self, app, db_session):
        """set_site_setting updates value when key already exists."""
        db_session.add(SiteSettings(key='update_key', value='old'))
        db_session.flush()

        set_site_setting('update_key', 'new', db_session=db_session)
        row = db_session.get(SiteSettings, 'update_key')
        assert row.value == 'new'

    def test_returns_row_object(self, app, db_session):
        """set_site_setting returns the SiteSettings row."""
        row = set_site_setting('ret_key', 'ret_val', db_session=db_session)
        assert isinstance(row, SiteSettings)
        assert row.key == 'ret_key'
        assert row.value == 'ret_val'

    def test_updated_at_set(self, app, db_session):
        """set_site_setting sets updated_at timestamp."""
        row = set_site_setting('ts_key', 'v', db_session=db_session)
        assert row.updated_at is not None


class TestEnsureDefaultsSeeded:
    """Tests for ensure_defaults_seeded()."""

    def test_seeds_missing_keys(self, app, db_session):
        """ensure_defaults_seeded creates rows for all missing default keys."""
        # Clear any rows inserted by earlier tests so we can check fresh seeds.
        db_session.query(SiteSettings).delete(synchronize_session=False)
        db_session.flush()

        ensure_defaults_seeded(db_session=db_session)
        for key, expected in SETTING_DEFAULTS.items():
            row = db_session.get(SiteSettings, key)
            assert row is not None, f'Expected row for key {key!r}'
            assert row.value == expected

    def test_idempotent(self, app, db_session):
        """Calling ensure_defaults_seeded twice does not raise or duplicate rows."""
        ensure_defaults_seeded(db_session=db_session)
        ensure_defaults_seeded(db_session=db_session)
        count = db_session.query(SiteSettings).count()
        assert count >= len(SETTING_DEFAULTS)


class TestSettingMeta:
    """SETTING_META mirrors SETTING_DEFAULTS and carries metadata for the UI."""

    def test_meta_covers_every_default_key(self):
        for key in SETTING_DEFAULTS:
            assert key in SETTING_META, f'Missing SETTING_META entry for {key!r}'
            assert 'type' in SETTING_META[key]
            assert 'description' in SETTING_META[key]
            assert SETTING_META[key]['description']

    def test_meta_types_are_known(self):
        allowed_types = {'bool', 'int', 'str', 'email', 'url'}
        for key, meta in SETTING_META.items():
            assert meta['type'] in allowed_types, (
                f'{key!r} has unknown type {meta["type"]!r}'
            )


class TestValidateSettingValue:
    """validate_setting_value coerces and validates raw form input."""

    @pytest.mark.parametrize('raw,expected', [
        ('true', 'true'),
        ('false', 'false'),
        ('1', 'true'),
        ('0', 'false'),
        ('on', 'true'),
        ('off', 'false'),
        ('', 'false'),
        (' YES ', 'true'),
        ('No', 'false'),
    ])
    def test_bool_normalisation(self, raw, expected):
        assert validate_setting_value('default_linear_plan', raw) == expected

    def test_bool_invalid_raises(self):
        with pytest.raises(SettingValidationError):
            validate_setting_value('default_linear_plan', 'maybe')

    def test_int_basic(self):
        assert validate_setting_value('referral_bonus_xp', '42') == '42'

    def test_int_empty_falls_back_to_default(self):
        assert validate_setting_value('referral_bonus_xp', '') == '100'

    def test_int_clamps_to_min(self):
        assert validate_setting_value('referral_bonus_xp', '-50') == '0'

    def test_int_clamps_to_max(self):
        assert validate_setting_value('referral_bonus_xp', '99999') == '10000'

    def test_int_invalid_raises(self):
        with pytest.raises(SettingValidationError):
            validate_setting_value('referral_bonus_xp', 'abc')

    def test_email_valid(self):
        assert validate_setting_value('support_email', 'help@x.com') == 'help@x.com'

    def test_email_empty_allowed(self):
        assert validate_setting_value('support_email', '') == ''

    def test_email_invalid_raises(self):
        with pytest.raises(SettingValidationError):
            validate_setting_value('support_email', 'not-an-email')

    def test_url_valid(self):
        assert (
            validate_setting_value('og_image_url', 'https://example.com/og.png')
            == 'https://example.com/og.png'
        )

    def test_url_invalid_scheme_raises(self):
        with pytest.raises(SettingValidationError):
            validate_setting_value('og_image_url', 'example.com/og.png')

    def test_str_max_length(self):
        with pytest.raises(SettingValidationError):
            validate_setting_value('site_title', 'a' * 250)

    def test_unknown_key_treated_as_string(self):
        # An unknown key falls back to type='str' with no max_length.
        assert validate_setting_value('totally_unknown_key', '  hi  ') == 'hi'
