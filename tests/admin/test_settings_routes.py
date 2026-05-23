"""Tests for admin settings page (Task 2)."""
import uuid
import pytest
from unittest.mock import patch

from app.admin.site_settings import SiteSettings, get_site_setting, set_site_setting
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
            'referral_bonus_days': '7',
        }, follow_redirects=True)
        assert response.status_code == 200

        with app.app_context():
            value = get_site_setting('site_title')
            assert value == 'My Custom Title'

    def test_post_saves_bool_true_when_checkbox_present(self, app, client, admin_user):
        client.post('/admin/settings', data={
            'default_linear_plan': '1',
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
            'referral_bonus_days': '7',
        }, follow_redirects=True)

        with app.app_context():
            value = get_site_setting('default_linear_plan')
            assert value == 'true'

    def test_post_saves_bool_false_when_checkbox_absent(self, app, client, admin_user, db_session):
        set_site_setting('default_mission_plan', 'true', db_session=db_session)
        db_session.commit()

        client.post('/admin/settings', data={
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
            'referral_bonus_days': '7',
        }, follow_redirects=True)

        with app.app_context():
            value = get_site_setting('default_mission_plan')
            assert value == 'false'

    def test_post_saves_int_value(self, app, client, admin_user):
        client.post('/admin/settings', data={
            'referral_bonus_xp': '100',
            'referral_bonus_days': '14',
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
        }, follow_redirects=True)

        with app.app_context():
            assert get_site_setting('referral_bonus_xp') == '100'
            assert get_site_setting('referral_bonus_days') == '14'

    def test_post_redirects_to_settings_page(self, app, client, admin_user):
        response = client.post('/admin/settings', data={
            'site_title': '',
            'site_description': '',
            'og_image_url': '',
            'meta_keywords': '',
            'support_email': '',
            'support_phone': '',
            'referral_bonus_xp': '50',
            'referral_bonus_days': '7',
        })
        assert response.status_code == 302
        assert '/admin/settings' in response.headers['Location']


class TestFeatureFlagOnRegistration:
    """Feature flags from SiteSettings applied during user registration."""

    @patch('app.auth.routes.email_sender')
    def test_default_linear_plan_applied_on_register(self, mock_email, app, client, db_session):
        from app.auth.models import User
        mock_email.send_email.return_value = True
        set_site_setting('default_linear_plan', 'true', db_session=db_session)
        db_session.commit()

        username = f'newuser_{uuid.uuid4().hex[:6]}'
        resp = client.post('/register', data={
            'username': username,
            'email': f'{username}@test.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert resp.status_code == 302, f'Expected redirect, got {resp.status_code}'

        user = db_session.query(User).filter_by(username=username).first()
        assert user is not None, 'Registration failed — user was not created'
        assert user.use_linear_plan is True

    @patch('app.auth.routes.email_sender')
    def test_default_mission_plan_not_applied_when_false(self, mock_email, app, client, db_session):
        from app.auth.models import User
        mock_email.send_email.return_value = True
        set_site_setting('default_mission_plan', 'false', db_session=db_session)
        db_session.commit()

        username = f'newuser2_{uuid.uuid4().hex[:6]}'
        resp = client.post('/register', data={
            'username': username,
            'email': f'{username}@test.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert resp.status_code == 302, f'Expected redirect, got {resp.status_code}'

        user = db_session.query(User).filter_by(username=username).first()
        assert user is not None, 'Registration failed — user was not created'
        assert user.use_mission_plan is False
