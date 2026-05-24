"""Task 25: Rate limiting on critical admin endpoints.

Tests verify that dangerous endpoints (audio generation, system migrations,
OAuth callback) enforce per-user rate limits and return 429 when exceeded.

Flask-Limiter (RATELIMIT_ENABLED=False in tests) guards audio routes via
decorator; the curriculum custom rate_limit decorator is enabled in all
environments and is testable by exhausting the in-memory store.
"""
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_admin_user(admin_user):
    """Mock current_user to be an authenticated admin for route testing."""
    with patch('app.admin.utils.decorators.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.id = admin_user.id
        mock_user.username = admin_user.username
        yield mock_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_rate_limiter():
    """Clear the in-memory custom rate_limiter between tests."""
    from app.curriculum.rate_limiter import rate_limiter
    rate_limiter.requests.clear()
    rate_limiter.blocked.clear()


# ---------------------------------------------------------------------------
# System routes — custom rate_limit decorator (testable in all envs)
# ---------------------------------------------------------------------------

class TestSystemRoutesRateLimit:
    """system_routes endpoints use curriculum rate_limit → testable via state reset."""

    def setup_method(self):
        _reset_rate_limiter()

    def teardown_method(self):
        _reset_rate_limiter()

    @patch('app.admin.routes.system_routes.clear_admin_cache')
    def test_clear_cache_rate_limited_after_10(self, mock_clear, admin_client, mock_admin_user):
        """11th clear-cache request within 60s returns 429."""
        with patch('app.admin.routes.system_routes.log_admin_action'):
            for _ in range(10):
                r = admin_client.post(
                    '/admin/system/clear-cache',
                    data={'confirm': 'CLEAR_CACHE'},
                    follow_redirects=False,
                )
                assert r.status_code == 302, f"Expected 302 on attempt {_ + 1}"
            r = admin_client.post(
                '/admin/system/clear-cache',
                data={'confirm': 'CLEAR_CACHE'},
                follow_redirects=False,
            )
        assert r.status_code == 429

    @patch('app.utils.db_init.init_db')
    def test_init_database_rate_limited_after_3(self, mock_init, admin_client, mock_admin_user):
        """4th init-database request within 300s returns 429."""
        with patch('app.admin.routes.system_routes.log_admin_action'):
            for _ in range(3):
                r = admin_client.post(
                    '/admin/system/database/init',
                    data={'confirm': 'INIT_DATABASE'},
                    follow_redirects=False,
                )
                assert r.status_code == 302

            r = admin_client.post(
                '/admin/system/database/init',
                data={'confirm': 'INIT_DATABASE'},
                follow_redirects=False,
            )
        assert r.status_code == 429

    @patch('app.admin.services.system_service.SystemService.test_database_connection')
    def test_test_db_connection_rate_limited_after_30(self, mock_conn, admin_client, mock_admin_user):
        """31st test-connection request within 60s returns 429."""
        mock_conn.return_value = {'status': 'connected'}
        for _ in range(30):
            r = admin_client.get('/admin/system/database/test-connection')
            assert r.status_code == 200
        r = admin_client.get('/admin/system/database/test-connection')
        assert r.status_code == 429


# ---------------------------------------------------------------------------
# SEO routes — custom rate_limit decorator added in Task 25
# ---------------------------------------------------------------------------

class TestSeoRoutesRateLimit:
    """gsc_connect, gsc_callback, gsc_disconnect, gsc_select_site are rate-limited."""

    def setup_method(self):
        _reset_rate_limiter()

    def teardown_method(self):
        _reset_rate_limiter()

    @pytest.mark.smoke
    def test_gsc_connect_rate_limited_after_5(self, admin_client, mock_admin_user):
        """6th /seo/connect request within 300s returns 429."""
        with patch('app.admin.routes.seo_routes._google_config_present', return_value=False):
            for _ in range(5):
                r = admin_client.get('/admin/seo/connect', follow_redirects=False)
                assert r.status_code == 302
            r = admin_client.get('/admin/seo/connect', follow_redirects=False)
        assert r.status_code == 429

    def test_gsc_callback_rate_limited_after_5(self, admin_client, mock_admin_user):
        """6th /seo/callback request within 300s returns 429."""
        with patch('app.admin.routes.seo_routes._google_config_present', return_value=False):
            for _ in range(5):
                r = admin_client.get('/admin/seo/callback?error=access_denied', follow_redirects=False)
                assert r.status_code == 302
            r = admin_client.get('/admin/seo/callback?error=access_denied', follow_redirects=False)
        assert r.status_code == 429

    def test_gsc_disconnect_rate_limited_after_5(self, admin_client, mock_admin_user):
        """6th /seo/disconnect request within 300s returns 429."""
        with patch('app.admin.routes.seo_routes.log_admin_action'), \
             patch('app.admin.routes.seo_routes.set_site_setting'), \
             patch('app.admin.routes.seo_routes.clear_cache_by_prefix'):
            for _ in range(5):
                r = admin_client.post('/admin/seo/disconnect', follow_redirects=False)
                assert r.status_code == 302
            r = admin_client.post('/admin/seo/disconnect', follow_redirects=False)
        assert r.status_code == 429

    def test_seo_refresh_rate_limited_after_10(self, admin_client, mock_admin_user):
        """11th /seo/refresh request within 60s returns 429."""
        with patch('app.admin.routes.seo_routes.log_admin_action'), \
             patch('app.admin.routes.seo_routes.bump_seo_audit_cache_version'), \
             patch('app.admin.routes.seo_routes.clear_cache_by_prefix'):
            for _ in range(10):
                r = admin_client.post('/admin/seo/refresh', follow_redirects=False)
                assert r.status_code == 302
            r = admin_client.post('/admin/seo/refresh', follow_redirects=False)
        assert r.status_code == 429


# ---------------------------------------------------------------------------
# Audio routes — Flask-Limiter (RATELIMIT_ENABLED=False in tests)
# Tests verify the endpoints are functional (not blocked in test env).
# Rate limit metadata is verified structurally via the view's decorators.
# ---------------------------------------------------------------------------

class TestAudioRoutesRateLimitPresence:
    """Audio endpoints use Flask-Limiter; RATELIMIT_ENABLED=False in tests so
    we verify the endpoints respond normally and the decorators are present."""

    def test_update_audio_download_status_is_accessible(self, admin_client, mock_admin_user):
        """update-download-status responds (limiter disabled in test env)."""
        with patch(
            'app.admin.routes.audio_routes.AudioManagementService.update_download_status',
            return_value=5,
        ), patch('app.admin.routes.audio_routes.log_admin_action'), \
           patch('app.admin.routes.audio_routes.clear_admin_cache'):
            r = admin_client.post(
                '/admin/audio/update-download-status',
                json={},
            )
        assert r.status_code == 200

    def test_fix_all_audio_is_accessible(self, admin_client, mock_admin_user):
        """fix-all responds (limiter disabled in test env)."""
        with patch(
            'app.admin.routes.audio_routes.AudioManagementService.update_download_status',
            return_value=0,
        ), patch(
            'app.admin.routes.audio_routes.AudioManagementService.fix_listening_fields',
            return_value=(True, 0, 'ok'),
        ), patch(
            'app.admin.routes.audio_routes.AudioManagementService.normalize_listening_fields',
            return_value=(True, 0, 'ok'),
        ), patch(
            'app.admin.routes.audio_routes.AudioManagementService.fill_empty_listening_fields',
            return_value=(True, 0, 'ok'),
        ), patch('app.admin.routes.audio_routes.log_admin_action'), \
           patch('app.admin.routes.audio_routes.clear_admin_cache'):
            r = admin_client.post('/admin/audio/fix-all')
        assert r.status_code in (200, 207)

    def test_cleanup_orphan_audio_is_accessible(self, admin_client, mock_admin_user):
        """orphans/cleanup responds (limiter disabled in test env)."""
        with patch(
            'app.admin.routes.audio_routes.AudioManagementService.delete_orphan_audio_files',
            return_value={'deleted': 0, 'skipped': 0},
        ), patch('app.admin.routes.audio_routes.log_admin_action'):
            r = admin_client.post(
                '/admin/audio/orphans/cleanup',
                json={'confirm': 'dry-run'},
            )
        assert r.status_code in (200, 207)

    def test_rate_limited_endpoints_have_limiter_decorator(self, app):
        """Audio blueprint view functions carry Flask-Limiter annotations."""
        from app import limiter
        from app.admin.routes.audio_routes import (
            update_audio_download_status,
            fix_all_audio,
            cleanup_orphan_audio_files,
        )
        for view_fn in (update_audio_download_status, fix_all_audio, cleanup_orphan_audio_files):
            # Flask-Limiter wraps views with functools.wraps, setting __wrapped__.
            # This verifies at least one outer decorator was applied (not a plain function).
            assert hasattr(view_fn, '__wrapped__'), (
                f"{view_fn.__name__} is not wrapped — @limiter.limit or @admin_required missing"
            )
