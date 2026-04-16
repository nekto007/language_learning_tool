"""Tests for rate limiting on auth endpoints.

Rate limiting is disabled globally in tests (RATELIMIT_ENABLED=False in conftest).
These tests create a separate app instance with rate limiting enabled so we can
verify 429 responses are returned when limits are exceeded.
"""
import pytest
from config.settings import Config


@pytest.fixture(scope='module')
def rl_app():
    """Separate app instance with rate limiting enabled for these tests only."""
    from app import create_app, limiter

    class RLTestConfig(Config):
        TESTING = True
        WTF_CSRF_ENABLED = False
        SERVER_NAME = 'localhost'
        RATELIMIT_ENABLED = True
        RATELIMIT_STORAGE_URI = 'memory://'
        SQLALCHEMY_DATABASE_URI = Config.SQLALCHEMY_DATABASE_URI

    app = create_app(config_class=RLTestConfig)
    return app


@pytest.fixture
def rl_client(rl_app):
    """Test client with rate limiting enabled; resets limiter state per test."""
    from app import limiter
    with rl_app.app_context():
        try:
            limiter.reset()
        except Exception:
            pass
    with rl_app.test_client() as client:
        yield client
    with rl_app.app_context():
        try:
            limiter.reset()
        except Exception:
            pass


@pytest.mark.smoke
def test_register_rate_limit_returns_429(rl_client):
    """Exceeding 5-per-minute limit on /register returns 429."""
    # Hit the limit (5 requests allowed per minute)
    for i in range(5):
        resp = rl_client.get('/register')
        assert resp.status_code in (200, 302), f"Request {i+1} should not be rate-limited yet"

    # 6th request must be rate-limited
    resp = rl_client.get('/register')
    assert resp.status_code == 429


def test_password_reset_rate_limit_returns_429(rl_client):
    """Exceeding 3-per-hour limit on /reset_password returns 429."""
    # Hit the limit (3 requests allowed per hour)
    for i in range(3):
        resp = rl_client.get('/reset_password')
        assert resp.status_code in (200, 302), f"Request {i+1} should not be rate-limited yet"

    # 4th request must be rate-limited
    resp = rl_client.get('/reset_password')
    assert resp.status_code == 429


def test_login_not_rate_limited_under_threshold(rl_client):
    """Login endpoint allows 10 requests per minute; 5 requests should pass."""
    for i in range(5):
        resp = rl_client.get('/login')
        assert resp.status_code in (200, 302), f"Request {i+1} should not be rate-limited"
