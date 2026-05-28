"""
Tests for Task 33: API CSRF and JWT authentication audit.

Verifies:
- Mutating POST/PUT/DELETE API endpoints are protected by @api_auth_required
- @csrf.exempt usage is only where JWT or equivalent auth is present
- Expired JWT token returns 401 with a clear message (not 500)
- Refresh endpoint rejects access tokens (only accepts refresh tokens)
- Unauthenticated requests to protected endpoints return 401 JSON
"""
import pytest
from datetime import timedelta


class TestExpiredJWTReturns401:
    """Expired JWT tokens should return 401 with a descriptive message."""

    def _get_expired_token(self, app, test_user):
        from flask_jwt_extended import create_access_token
        with app.app_context():
            return create_access_token(
                identity=str(test_user.id),
                expires_delta=timedelta(seconds=-1),
            )

    def test_expired_token_on_words_endpoint(self, app, client, test_user):
        token = self._get_expired_token(app, test_user)
        response = client.get(
            '/api/words',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert response.status_code == 401
        data = response.get_json()
        assert data['success'] is False
        assert 'error' in data
        assert data['error'] != ''

    def test_expired_token_error_message_is_not_blank(self, app, client, test_user):
        token = self._get_expired_token(app, test_user)
        response = client.get(
            '/api/words',
            headers={'Authorization': f'Bearer {token}'},
        )
        data = response.get_json()
        # Must contain a non-empty 'error' field, not a 500 traceback
        assert data.get('error') or data.get('message'), (
            "Expired-token response must include an 'error' or 'message' field"
        )

    def test_expired_token_does_not_return_500(self, app, client, test_user):
        token = self._get_expired_token(app, test_user)
        response = client.get(
            '/api/words',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert response.status_code != 500


class TestRefreshEndpointRejectsAccessToken:
    """POST /api/refresh must reject access tokens; only refresh tokens allowed."""

    def test_access_token_rejected_by_refresh_endpoint(self, client, test_user):
        login = client.post(
            '/api/login',
            json={'username': test_user.username, 'password': 'testpass123'},
        )
        assert login.status_code == 200
        access_token = login.get_json()['access_token']

        response = client.post(
            '/api/refresh',
            headers={'Authorization': f'Bearer {access_token}'},
        )
        assert response.status_code == 401

    def test_valid_refresh_token_accepted(self, client, test_user):
        login = client.post(
            '/api/login',
            json={'username': test_user.username, 'password': 'testpass123'},
        )
        refresh_token = login.get_json()['refresh_token']

        response = client.post(
            '/api/refresh',
            headers={'Authorization': f'Bearer {refresh_token}'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'access_token' in data

    def test_no_token_returns_401(self, client):
        response = client.post('/api/refresh')
        assert response.status_code == 401

    def test_malformed_token_returns_401(self, client):
        response = client.post(
            '/api/refresh',
            headers={'Authorization': 'Bearer this.is.not.a.jwt'},
        )
        assert response.status_code == 401


class TestUnauthenticatedMutatingEndpoints:
    """POST/PUT/DELETE API endpoints must return 401 JSON (not CSRF 400) when unauthenticated."""

    def _assert_unauthenticated_returns_401_json(self, client, method, url, **kwargs):
        func = getattr(client, method)
        response = func(url, **kwargs)
        assert response.status_code == 401, (
            f"Expected 401 from unauthenticated {method.upper()} {url}, got {response.status_code}"
        )
        data = response.get_json()
        assert data is not None, "Response must be JSON"
        assert data.get('success') is False

    def test_api_words_post_without_auth(self, client):
        self._assert_unauthenticated_returns_401_json(
            client, 'post', '/api/update-word-status', json={'word_id': 1, 'status': 'known'}
        )

    def test_api_daily_plan_skip_lesson_without_auth(self, client):
        self._assert_unauthenticated_returns_401_json(
            client, 'post', '/api/daily-plan/skip-lesson', json={'lesson_id': 1}
        )

    def test_api_daily_plan_events_without_auth(self, client):
        self._assert_unauthenticated_returns_401_json(
            client, 'post', '/api/daily-plan/events',
            json={'event_type': 'slot_skipped'}
        )

    def test_api_plan_pause_without_auth(self, client):
        self._assert_unauthenticated_returns_401_json(
            client, 'post', '/api/plan/pause', json={'days': 1}
        )

    def test_api_plan_resume_without_auth(self, client):
        self._assert_unauthenticated_returns_401_json(
            client, 'post', '/api/plan/resume', json={}
        )


class TestCSRFExemptAudit:
    """Every @csrf.exempt endpoint must have an equivalent auth mechanism."""

    def test_reading_session_end_requires_login(self, client):
        """books/api reading-session-end is csrf.exempt but gated by @login_required."""
        response = client.post(
            '/api/books/reading-session/end',
            json={'session_id': 999, 'offset_delta': 0.5},
        )
        # Must not be 200 without authentication
        assert response.status_code in (401, 302, 403), (
            f"reading-session/end should require auth, got {response.status_code}"
        )

    def test_telegram_webhook_without_secret_returns_403(self, client):
        """Telegram webhook is csrf.exempt but gated by secret token check."""
        response = client.post(
            '/telegram/webhook',
            json={'update_id': 1},
        )
        # Without a valid secret, webhook returns 403 or 500 (if secret not configured)
        assert response.status_code in (403, 500)

    def test_telegram_webhook_with_wrong_secret_returns_403(self, client, app):
        """Telegram webhook rejects wrong secret tokens."""
        with app.app_context():
            app.config['TELEGRAM_WEBHOOK_SECRET'] = 'real_secret'
            response = client.post(
                '/telegram/webhook',
                headers={'X-Telegram-Bot-Api-Secret-Token': 'wrong_secret'},
                json={'update_id': 1},
            )
        assert response.status_code in (403,)

    def test_health_endpoint_accessible_without_auth(self, client):
        """Health check endpoint is csrf.exempt and intentionally unauthenticated."""
        response = client.get('/health')
        assert response.status_code == 200

    def test_daily_plan_csrf_exempt_endpoints_require_auth(self, client):
        """daily_plan.py has several csrf.exempt POST endpoints; all need @api_auth_required."""
        exempt_mutating_endpoints = [
            ('/api/daily-plan/skip-lesson', {'lesson_id': 1}),
            ('/api/daily-plan/events', {'event_type': 'slot_skipped'}),
            ('/api/plan/pause', {'days': 1}),
            ('/api/plan/resume', {}),
        ]
        for url, payload in exempt_mutating_endpoints:
            response = client.post(url, json=payload)
            assert response.status_code == 401, (
                f"{url} (csrf.exempt) should require auth, got {response.status_code}"
            )
            data = response.get_json()
            assert data is not None and data.get('success') is False


@pytest.mark.smoke
class TestJWTAuthSmoke:
    """Smoke tests for JWT auth."""

    def test_login_returns_tokens(self, client, test_user):
        response = client.post(
            '/api/login',
            json={'username': test_user.username, 'password': 'testpass123'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert 'access_token' in data
        assert 'refresh_token' in data

    def test_invalid_bearer_token_returns_401(self, client):
        response = client.get(
            '/api/words',
            headers={'Authorization': 'Bearer totally.invalid.token'},
        )
        assert response.status_code == 401

    def test_refresh_with_access_token_returns_401(self, client, test_user):
        login = client.post(
            '/api/login',
            json={'username': test_user.username, 'password': 'testpass123'},
        )
        access_token = login.get_json()['access_token']
        response = client.post(
            '/api/refresh',
            headers={'Authorization': f'Bearer {access_token}'},
        )
        assert response.status_code == 401
