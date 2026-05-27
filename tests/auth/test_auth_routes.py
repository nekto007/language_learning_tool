"""
Auth routes: redirect safety, session clearing, remember_me bypass, JWT refresh.
"""
import pytest
import uuid
from unittest.mock import patch

from app.auth.models import User
from app.utils.db import db


# ---------------------------------------------------------------------------
# ?next= open redirect protection
# ---------------------------------------------------------------------------

class TestOpenRedirectProtection:
    """Comprehensive open redirect tests for all ?next= entry points."""

    def _login(self, client, user, next_url=None):
        url = '/login'
        if next_url:
            url += f'?next={next_url}'
        return client.post(url, data={
            'username_or_email': user.username,
            'password': 'testpass123',
        }, follow_redirects=False)

    def test_blocks_protocol_relative_url(self, client, test_user):
        r = self._login(client, test_user, '//evil.com')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'evil.com' not in loc

    def test_blocks_backslash_trick(self, client, test_user):
        r = self._login(client, test_user, '/\\evil.com')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'evil.com' not in loc

    def test_blocks_data_url(self, client, test_user):
        r = self._login(client, test_user, 'data:text/html,<h1>xss</h1>')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'data:' not in loc

    def test_blocks_ftp_scheme(self, client, test_user):
        r = self._login(client, test_user, 'ftp://evil.com')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'ftp' not in loc

    def test_allows_internal_path_with_hash(self, client, test_user):
        r = self._login(client, test_user, '/study/#section')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert '/study/' in loc

    def test_relative_path_without_slash_rejected(self, client, test_user):
        r = self._login(client, test_user, 'evil.com')
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'evil.com' not in loc

    @pytest.mark.smoke
    def test_get_safe_redirect_url_unit(self, app):
        from app.auth.routes import get_safe_redirect_url
        with app.test_request_context():
            assert get_safe_redirect_url('//evil.com', 'auth.login').startswith('/')
            assert 'evil.com' not in get_safe_redirect_url('//evil.com', 'auth.login')
            assert get_safe_redirect_url('/study/', 'auth.login') == '/study/'
            assert get_safe_redirect_url('/\\evil.com', 'auth.login').startswith('/')
            assert 'evil.com' not in get_safe_redirect_url('/\\evil.com', 'auth.login')


# ---------------------------------------------------------------------------
# Session clearing after logout
# ---------------------------------------------------------------------------

class TestSessionClearingOnLogout:
    """After logout, session must be fully cleared — no protected resource accessible."""

    @pytest.mark.smoke
    def test_protected_route_returns_redirect_after_logout(self, authenticated_client):
        r_before = authenticated_client.get('/profile', follow_redirects=False)
        assert r_before.status_code == 200

        authenticated_client.get('/logout', follow_redirects=False)

        r_after = authenticated_client.get('/profile', follow_redirects=False)
        assert r_after.status_code in (302, 401)

    def test_logout_clears_user_id_from_session(self, client, test_user):
        client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)

        with client.session_transaction() as session:
            assert '_user_id' in session

        client.get('/logout', follow_redirects=False)

        with client.session_transaction() as session:
            assert '_user_id' not in session

    def test_double_logout_does_not_crash(self, authenticated_client):
        authenticated_client.get('/logout', follow_redirects=False)
        r = authenticated_client.get('/logout', follow_redirects=False)
        assert r.status_code in (302, 401)

    def test_logout_redirects_to_login(self, authenticated_client):
        r = authenticated_client.get('/logout', follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert '/login' in loc

    def test_api_endpoint_inaccessible_after_logout(self, authenticated_client):
        r_before = authenticated_client.get('/profile')
        assert r_before.status_code == 200

        authenticated_client.get('/logout')

        r_after = authenticated_client.get('/profile', follow_redirects=False)
        assert r_after.status_code in (302, 401)


# ---------------------------------------------------------------------------
# remember_me token does not bypass is_active check
# ---------------------------------------------------------------------------

class TestRememberMeDoesNotBypassIsActive:
    """Flask-Login must not grant access to inactive users via remember_me."""

    @pytest.mark.smoke
    def test_inactive_user_cannot_access_protected_route(self, client, db_session, test_user):
        # Log in while active
        client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)

        # Deactivate while session is still valid
        test_user.active = False
        db_session.commit()

        # Flask-Login re-checks is_active on every request via user_loader
        r = client.get('/profile', follow_redirects=False)
        assert r.status_code in (302, 401)

    def test_login_with_remember_me_false_and_inactive(self, client, db_session, test_user):
        test_user.active = False
        db_session.commit()

        r = client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
            'remember_me': 'y',
        }, follow_redirects=True)
        # Should not be logged in
        assert r.status_code == 200
        body = r.data.decode().lower()
        assert 'неактивна' in body or 'inactive' in body


# ---------------------------------------------------------------------------
# JWT refresh endpoint — token type enforcement
# ---------------------------------------------------------------------------

class TestJWTRefreshEndpoint:
    """JWT refresh must require a refresh token, not an access token."""

    @pytest.mark.smoke
    def test_refresh_with_access_token_fails(self, client, test_user, app):
        from flask_jwt_extended import create_access_token
        with app.app_context():
            access_token = create_access_token(identity=str(test_user.id))

        r = client.post('/api/refresh', headers={
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        })
        assert r.status_code in (401, 422)

    def test_refresh_without_token_fails(self, client):
        r = client.post('/api/refresh', headers={
            'Content-Type': 'application/json',
        })
        assert r.status_code in (401, 422)

    def test_refresh_with_invalid_token_fails(self, client):
        r = client.post('/api/refresh', headers={
            'Authorization': 'Bearer this.is.invalid',
            'Content-Type': 'application/json',
        })
        assert r.status_code in (401, 422)

    def test_refresh_with_valid_refresh_token_succeeds(self, client, test_user, app):
        from flask_jwt_extended import create_refresh_token
        with app.app_context():
            refresh_token = create_refresh_token(
                identity=str(test_user.id),
                additional_claims={'username': test_user.username, 'is_admin': False},
            )

        r = client.post('/api/refresh', headers={
            'Authorization': f'Bearer {refresh_token}',
            'Content-Type': 'application/json',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert 'access_token' in data


# ---------------------------------------------------------------------------
# API login — is_active check
# ---------------------------------------------------------------------------

class TestAPILoginIsActiveCheck:
    """POST /api/auth/login must reject inactive users."""

    def test_inactive_user_gets_403(self, client, db_session, test_user):
        test_user.active = False
        db_session.commit()

        r = client.post('/api/login', json={
            'username': test_user.username,
            'password': 'testpass123',
        })
        assert r.status_code == 403
        data = r.get_json()
        assert data.get('error') == 'account_inactive'

    def test_active_user_gets_tokens(self, client, test_user):
        r = client.post('/api/login', json={
            'username': test_user.username,
            'password': 'testpass123',
        })
        assert r.status_code == 200
        data = r.get_json()
        assert 'access_token' in data
        assert 'refresh_token' in data
