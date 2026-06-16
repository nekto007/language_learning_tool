"""Tests for admin settings page (Task 2)."""
import uuid
import pytest
from unittest.mock import patch

from app.admin.audit import AdminAuditLog
from app.admin.site_settings import (
    SETTING_META,
    SiteSettings,
    get_site_setting,
    set_site_setting,
)
from app.utils.db import db


class TestSettingsGET:
    """GET /admin/settings renders the form."""

    @pytest.mark.smoke
    def test_get_renders_200(self, app, client, admin_user):
        response = client.get('/admin/settings')
        assert response.status_code == 200

    def test_get_contains_section_headings(self, app, client, admin_user):
        response = client.get('/admin/settings')
        html = response.data.decode()
        assert 'Флаги фич' in html
        assert 'SEO' in html
        assert 'Контакты' in html
        assert 'Реферальная' in html

    def test_get_shows_existing_value(self, app, client, admin_user, db_session):
        set_site_setting('support_email', 'test@example.com', db_session=db_session)
        db_session.commit()

        response = client.get('/admin/settings')
        html = response.data.decode()
        assert 'test@example.com' in html

    def test_get_renders_setting_descriptions(self, app, client, admin_user):
        """The settings page exposes the human-readable description from SETTING_META."""
        response = client.get('/admin/settings')
        html = response.data.decode()
        # Pick a representative description that is unique to our meta dict.
        expected = SETTING_META['referral_bonus_xp']['description']
        assert expected in html


class TestSettingsPOST:
    """POST /admin/settings saves values."""

    @pytest.mark.smoke
    def test_post_saves_text_value(self, app, client, admin_user):
        response = client.post('/admin/settings', data={
            'site_title': 'My Custom Title',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
        }, follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            value = get_site_setting('site_title')
            assert value == 'My Custom Title'

    def test_post_saves_bool_true_when_checkbox_present(self, app, client, admin_user):
        client.post('/admin/settings', data={
            'daily_race_enabled': '1',
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
        }, follow_redirects=True)

        with app.app_context():
            value = get_site_setting('daily_race_enabled')
            assert value == 'true'

    def test_post_saves_bool_false_when_checkbox_absent(self, app, client, admin_user, db_session):
        set_site_setting('daily_race_enabled', 'true', db_session=db_session)
        db_session.commit()

        client.post('/admin/settings', data={
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
        }, follow_redirects=True)

        with app.app_context():
            value = get_site_setting('daily_race_enabled')
            assert value == 'false'

    def test_post_saves_int_value(self, app, client, admin_user):
        client.post('/admin/settings', data={
            'referral_bonus_xp': '100',
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
        }, follow_redirects=True)

        with app.app_context():
            assert get_site_setting('referral_bonus_xp') == '100'

    def test_post_redirects_to_settings_page(self, app, client, admin_user):
        response = client.post('/admin/settings', data={
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
        })
        assert response.status_code == 302
        assert '/admin/settings' in response.headers['Location']


class TestSettingsValidation:
    """Submitted values are validated before any DB write."""

    def test_invalid_email_rejected(self, app, client, admin_user, db_session):
        # Pre-seed a known value so we can verify it's untouched after a bad submit.
        set_site_setting('support_email', 'good@x.com', db_session=db_session)
        db_session.commit()

        response = client.post('/admin/settings', data={
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': 'not-an-email',
            'support_phone': '',
            'referral_bonus_xp': '50',
        }, follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            # The invalid value must not overwrite the pre-existing one.
            assert get_site_setting('support_email') == 'good@x.com'

    def test_invalid_url_rejected(self, app, client, admin_user, db_session):
        set_site_setting('og_image_url', 'https://example.com/og.png', db_session=db_session)
        db_session.commit()

        client.post('/admin/settings', data={
            'site_title': '',
            'site_description': '',
            'og_image_url': 'ftp://nope',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
        }, follow_redirects=True)

        with app.app_context():
            assert get_site_setting('og_image_url') == 'https://example.com/og.png'

    def test_int_out_of_range_clamps(self, app, client, admin_user):
        client.post('/admin/settings', data={
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '999999',
        }, follow_redirects=True)

        with app.app_context():
            assert get_site_setting('referral_bonus_xp') == '10000'


class TestSettingsAuditLog:
    """Each changed key writes an AdminAuditLog row scoped to that key."""

    def test_changed_key_writes_audit_row(self, app, client, admin_user, db_session):
        # Start with a known value so we can assert that *changing* it produces a row.
        set_site_setting('site_title', 'old title', db_session=db_session)
        db_session.commit()
        before = (
            db_session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == 'site_settings.update.site_title')
            .count()
        )

        client.post('/admin/settings', data={
            'site_title': 'New Title',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
        }, follow_redirects=True)

        after = (
            db_session.query(AdminAuditLog)
            .filter(AdminAuditLog.action == 'site_settings.update.site_title')
            .count()
        )
        assert after == before + 1

    def test_unchanged_keys_do_not_write_audit_rows(self, app, client, admin_user, db_session):
        # Establish a stable baseline for every editable key so a no-op submit
        # truly is a no-op (bool flags default to 'true' — without explicit
        # form values they'd flip to 'false' and look "changed").
        set_site_setting('site_title', 'Stable', db_session=db_session)
        set_site_setting('referral_bonus_xp', '50', db_session=db_session)
        set_site_setting('daily_race_enabled', 'true', db_session=db_session)
        set_site_setting('streak_shield_enabled', 'true', db_session=db_session)
        db_session.commit()

        baseline = db_session.query(AdminAuditLog).count()

        client.post('/admin/settings', data={
            'site_title': 'Stable',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
            'daily_race_enabled': '1',
            'streak_shield_enabled': '1',
        }, follow_redirects=True)

        # No-op submit: nothing changed, so no audit rows should appear.
        assert db_session.query(AdminAuditLog).count() == baseline
