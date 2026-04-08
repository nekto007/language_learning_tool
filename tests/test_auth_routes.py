"""
Integration tests for app/auth/routes.py

Tests all auth endpoints:
- GET/POST /login
- GET/POST /register
- GET /logout
- GET/POST /reset_password
- GET/POST /reset_password/<token>
- GET/POST /profile
- GET/POST /change-password
"""
import pytest
import uuid
from unittest.mock import patch, MagicMock

from app.auth.models import User
from app.utils.db import db


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_login_page_renders(self, client):
        r = client.get('/login')
        assert r.status_code == 200

    def test_login_with_username(self, client, test_user):
        r = client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302

    def test_login_with_email(self, client, test_user):
        r = client.post('/login', data={
            'username_or_email': test_user.email,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302

    def test_login_wrong_password(self, client, test_user):
        r = client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'wrongpass',
        }, follow_redirects=False)
        assert r.status_code == 401

    def test_login_nonexistent_user(self, client):
        r = client.post('/login', data={
            'username_or_email': 'nonexistent_user_xyz',
            'password': 'whatever',
        }, follow_redirects=False)
        assert r.status_code == 401

    def test_login_inactive_user(self, client, db_session, test_user):
        test_user.active = False
        db_session.commit()
        r = client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_login_redirect_next(self, client, test_user):
        r = client.post('/login?next=/curriculum/api/levels', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/curriculum/api/levels' in r.headers.get('Location', '')

    def test_login_already_authenticated(self, authenticated_client):
        r = authenticated_client.get('/login', follow_redirects=False)
        assert r.status_code == 302

    def test_login_updates_last_login(self, client, db_session, test_user):
        old_login = test_user.last_login
        client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        db_session.refresh(test_user)
        assert test_user.last_login is not None
        if old_login:
            assert test_user.last_login >= old_login


# ---------------------------------------------------------------------------
# Safe redirect
# ---------------------------------------------------------------------------

class TestSafeRedirect:
    def test_blocks_external_url(self, client, test_user):
        r = client.post('/login?next=http://evil.com/steal', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'evil.com' not in loc

    def test_blocks_javascript_scheme(self, client, test_user):
        r = client.post('/login?next=javascript:alert(1)', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'javascript' not in loc


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

class TestRegister:
    def test_register_page_renders(self, client):
        r = client.get('/register')
        assert r.status_code == 200

    def test_register_already_authenticated(self, authenticated_client):
        r = authenticated_client.get('/register', follow_redirects=False)
        assert r.status_code == 302

    @patch('app.auth.routes.email_sender')
    def test_register_success(self, mock_email, client, db_session):
        mock_email.send_email.return_value = True
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'newuser_{unique}',
            'email': f'newuser_{unique}@example.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302

    @patch('app.auth.routes.email_sender')
    def test_register_auto_login_and_redirect_to_onboarding(self, mock_email, client, db_session):
        """After registration, user should be logged in and redirected to onboarding."""
        mock_email.send_email.return_value = True
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'newuser_{unique}',
            'email': f'newuser_{unique}@example.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302
        location = r.headers.get('Location', '')
        assert '/onboarding' in location

        # Verify user is logged in: accessing a login-required page should NOT
        # redirect to /login. It may return 200, 403, or redirect elsewhere.
        r2 = client.get('/dashboard', follow_redirects=False)
        if r2.status_code == 302:
            assert '/login' not in r2.headers.get('Location', '')

    @patch('app.auth.routes.email_sender')
    def test_register_sends_welcome_email(self, mock_email, client, db_session):
        """Registration should send a welcome email."""
        mock_email.send_email.return_value = True
        unique = uuid.uuid4().hex[:8]
        email = f'newuser_{unique}@example.com'
        client.post('/register', data={
            'username': f'newuser_{unique}',
            'email': email,
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        mock_email.send_email.assert_called_once()
        call_kwargs = mock_email.send_email.call_args
        assert call_kwargs[1]['to_email'] == email or call_kwargs[0][1] == email
        # Check template name is 'welcome'
        if call_kwargs[1].get('template_name'):
            assert call_kwargs[1]['template_name'] == 'welcome'
        else:
            assert 'welcome' in str(call_kwargs)

    @patch('app.auth.routes.email_sender')
    def test_register_succeeds_even_if_email_fails(self, mock_email, client, db_session):
        """Registration should succeed even if welcome email sending fails."""
        mock_email.send_email.side_effect = Exception("SMTP error")
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'newuser_{unique}',
            'email': f'newuser_{unique}@example.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302  # Still redirects to dashboard

    def test_register_duplicate_username(self, client, test_user):
        r = client.post('/register', data={
            'username': test_user.username,
            'email': 'different@example.com',
            'password': 'StrongPass123!@#',
            'password2': 'StrongPass123!@#',
        }, follow_redirects=True)
        assert r.status_code == 200  # Stays on form with error

    def test_register_duplicate_email(self, client, test_user):
        r = client.post('/register', data={
            'username': f'unique_{uuid.uuid4().hex[:8]}',
            'email': test_user.email,
            'password': 'StrongPass123!@#',
            'password2': 'StrongPass123!@#',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_register_password_mismatch(self, client):
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'user_{unique}',
            'email': f'user_{unique}@example.com',
            'password': 'StrongPass123!@#',
            'password2': 'DifferentPass!@#',
        }, follow_redirects=True)
        assert r.status_code == 200  # Form re-rendered with error


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_logout_redirects(self, authenticated_client):
        r = authenticated_client.get('/logout', follow_redirects=False)
        assert r.status_code == 302

    def test_logout_unauthenticated(self, client):
        r = client.get('/logout')
        assert r.status_code in [302, 401]


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class TestProfile:
    def test_profile_requires_login(self, client):
        r = client.get('/profile')
        assert r.status_code in [302, 401]


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

class TestChangePassword:
    def test_requires_login(self, client):
        r = client.get('/change-password')
        assert r.status_code in [302, 401]


# ---------------------------------------------------------------------------
# Password reset request
# ---------------------------------------------------------------------------

class TestPasswordResetRequest:
    def test_page_renders(self, client):
        r = client.get('/reset_password')
        assert r.status_code == 200

    def test_already_authenticated(self, authenticated_client):
        r = authenticated_client.get('/reset_password', follow_redirects=False)
        assert r.status_code == 302

    @patch('app.auth.routes.email_sender')
    def test_valid_email(self, mock_email, client, test_user):
        mock_email.send_email.return_value = True
        r = client.post('/reset_password', data={
            'email': test_user.email,
        }, follow_redirects=False)
        assert r.status_code in [302, 200]

    @patch('app.auth.routes.email_sender')
    def test_unknown_email_still_redirects(self, mock_email, client):
        """Should not reveal whether email exists."""
        r = client.post('/reset_password', data={
            'email': 'nonexistent@example.com',
        }, follow_redirects=True)
        assert r.status_code == 200

    @patch('app.auth.routes.email_sender')
    def test_email_send_failure(self, mock_email, client, test_user):
        mock_email.send_email.return_value = False
        r = client.post('/reset_password', data={
            'email': test_user.email,
        }, follow_redirects=True)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Password reset with token
# ---------------------------------------------------------------------------

class TestPasswordResetWithToken:
    def test_invalid_token(self, client):
        r = client.get('/reset_password/invalidtoken123')
        assert r.status_code in [302, 200]

    def test_valid_token_renders_form(self, client, test_user):
        from app.auth.routes import get_reset_token
        token = get_reset_token(test_user.id)
        r = client.get(f'/reset_password/{token}')
        assert r.status_code == 200

    def test_already_authenticated(self, authenticated_client):
        r = authenticated_client.get('/reset_password/sometoken', follow_redirects=False)
        assert r.status_code == 302


# ---------------------------------------------------------------------------
# Token generation / verification helpers
# ---------------------------------------------------------------------------

class TestTokenHelpers:
    def test_get_reset_token(self, app, test_user):
        from app.auth.routes import get_reset_token
        with app.app_context():
            token = get_reset_token(test_user.id)
            assert isinstance(token, str) and len(token) > 0

    def test_verify_reset_token(self, app, test_user):
        from app.auth.routes import get_reset_token, verify_reset_token
        with app.app_context():
            token = get_reset_token(test_user.id)
            uid = verify_reset_token(token)
            assert uid == test_user.id

    def test_verify_invalid_token(self, app):
        from app.auth.routes import verify_reset_token
        with app.app_context():
            assert verify_reset_token('totally_invalid') is None
