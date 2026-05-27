"""
Comprehensive tests for app/admin/routes/system_routes.py
Tests for system management, cache clearing, and database operations
"""
import pytest
from unittest.mock import patch, MagicMock
from flask import url_for

from app.admin.routes.system_routes import CLEAR_CACHE_CONFIRM, INIT_DATABASE_CONFIRM
from app.admin.services.system_service import mask_database_uri, sanitize_db_version


class TestClearCache:
    """Tests for clear_cache route"""

    @pytest.mark.smoke
    @patch('app.admin.routes.system_routes.clear_admin_cache')
    def test_clear_cache_success(self, mock_clear_cache, admin_client, mock_admin_user):
        response = admin_client.post(
            '/admin/system/clear-cache',
            data={'confirm': CLEAR_CACHE_CONFIRM},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.location.endswith('/admin/system')
        mock_clear_cache.assert_called_once()

    @patch('app.admin.routes.system_routes.clear_admin_cache')
    def test_clear_cache_rejects_missing_confirmation(self, mock_clear_cache, admin_client, mock_admin_user):
        response = admin_client.post('/admin/system/clear-cache', follow_redirects=False)
        assert response.status_code == 302
        mock_clear_cache.assert_not_called()

    @patch('app.admin.routes.system_routes.clear_admin_cache')
    def test_clear_cache_rejects_wrong_confirmation(self, mock_clear_cache, admin_client, mock_admin_user):
        response = admin_client.post(
            '/admin/system/clear-cache',
            data={'confirm': 'nope'},
            follow_redirects=False,
        )
        assert response.status_code == 302
        mock_clear_cache.assert_not_called()

    @patch('app.admin.routes.system_routes.clear_admin_cache')
    def test_clear_cache_error(self, mock_clear_cache, admin_client, mock_admin_user):
        mock_clear_cache.side_effect = Exception("Cache error")
        response = admin_client.post(
            '/admin/system/clear-cache',
            data={'confirm': CLEAR_CACHE_CONFIRM},
            follow_redirects=False,
        )
        assert response.status_code == 302
        mock_clear_cache.assert_called_once()

    def test_clear_cache_requires_admin(self, client):
        response = client.post(
            '/admin/system/clear-cache',
            data={'confirm': CLEAR_CACHE_CONFIRM},
        )
        assert response.status_code == 302  # Redirect to login


class TestSystemInfo:
    """Tests for system info route"""

    @patch('app.admin.routes.system_routes.render_template')
    @patch('app.admin.routes.system_routes.SystemService.get_system_info')
    def test_system_info_success(self, mock_get_info, mock_render, admin_client, mock_admin_user):
        mock_get_info.return_value = {
            'system_info': {'os': 'Linux', 'python': '3.9'},
            'db_stats': {'tables': 10},
            'app_info': {'version': '1.0'}
        }
        mock_render.return_value = '<html>system info</html>'
        response = admin_client.get('/admin/system')
        assert response.status_code == 200
        mock_get_info.assert_called_once()
        mock_render.assert_called_once()
        _, kwargs = mock_render.call_args
        assert kwargs.get('clear_cache_confirm') == CLEAR_CACHE_CONFIRM

    @patch('app.admin.routes.system_routes.SystemService.get_system_info')
    def test_system_info_error(self, mock_get_info, admin_client, mock_admin_user):
        mock_get_info.return_value = {'error': 'System error'}
        response = admin_client.get('/admin/system', follow_redirects=False)
        assert response.status_code == 302
        mock_get_info.assert_called_once()

    def test_system_info_requires_admin(self, client):
        response = client.get('/admin/system')
        assert response.status_code == 302


class TestDatabaseManagement:
    """Tests for database_management route"""

    @patch('app.admin.routes.system_routes.render_template')
    @patch('app.admin.routes.system_routes.SystemService.get_recent_db_operations')
    @patch('app.admin.routes.system_routes.SystemService.get_book_statistics')
    @patch('app.admin.routes.system_routes.SystemService.get_word_status_statistics')
    @patch('app.admin.routes.system_routes.SystemService.test_database_connection')
    def test_database_management_success(
        self,
        mock_test_conn,
        mock_word_stats,
        mock_book_stats,
        mock_recent_ops,
        mock_render,
        admin_client,
        mock_admin_user
    ):
        mock_test_conn.return_value = {'status': 'connected'}
        mock_word_stats.return_value = {'total': 1000}
        mock_book_stats.return_value = {'books': 50}
        mock_recent_ops.return_value = [{'op': 'insert', 'table': 'users'}]
        mock_render.return_value = '<html>database management</html>'

        response = admin_client.get('/admin/system/database')
        assert response.status_code == 200
        mock_test_conn.assert_called_once()
        mock_word_stats.assert_called_once()
        mock_book_stats.assert_called_once()
        mock_recent_ops.assert_called_once()
        mock_render.assert_called_once()
        _, kwargs = mock_render.call_args
        assert kwargs.get('init_db_confirm') == INIT_DATABASE_CONFIRM

    @patch('app.admin.routes.system_routes.SystemService.test_database_connection')
    def test_database_management_error(self, mock_test_conn, admin_client, mock_admin_user):
        mock_test_conn.side_effect = Exception("DB connection failed")
        response = admin_client.get('/admin/system/database')
        assert response.status_code == 200

    def test_database_management_requires_admin(self, client):
        response = client.get('/admin/system/database')
        assert response.status_code == 302


class TestInitDatabase:
    """Tests for init_database route"""

    @patch('app.utils.db_init.init_db')
    def test_init_database_success(self, mock_init_db, admin_client, mock_admin_user):
        response = admin_client.post(
            '/admin/system/database/init',
            data={'confirm': INIT_DATABASE_CONFIRM},
            follow_redirects=False,
        )
        assert response.status_code == 302
        assert response.location.endswith('/admin/system/database')
        mock_init_db.assert_called_once()

    @patch('app.utils.db_init.init_db')
    def test_init_database_rejects_missing_confirmation(self, mock_init_db, admin_client, mock_admin_user):
        response = admin_client.post('/admin/system/database/init', follow_redirects=False)
        assert response.status_code == 302
        mock_init_db.assert_not_called()

    @patch('app.utils.db_init.init_db')
    def test_init_database_rejects_wrong_confirmation(self, mock_init_db, admin_client, mock_admin_user):
        response = admin_client.post(
            '/admin/system/database/init',
            data={'confirm': 'init please'},
            follow_redirects=False,
        )
        assert response.status_code == 302
        mock_init_db.assert_not_called()

    @patch('app.utils.db_init.init_db')
    def test_init_database_error(self, mock_init_db, admin_client, mock_admin_user):
        mock_init_db.side_effect = Exception("Init failed")
        response = admin_client.post(
            '/admin/system/database/init',
            data={'confirm': INIT_DATABASE_CONFIRM},
            follow_redirects=False,
        )
        assert response.status_code == 302
        mock_init_db.assert_called_once()

    def test_init_database_requires_admin(self, client):
        response = client.post(
            '/admin/system/database/init',
            data={'confirm': INIT_DATABASE_CONFIRM},
        )
        assert response.status_code == 302


class TestRateLimit:
    """Verify dangerous endpoints enforce per-user rate limits."""

    @patch('app.utils.db_init.init_db')
    def test_init_database_rate_limit(self, mock_init_db, admin_client, mock_admin_user):
        # 3 allowed per 300s; 4th must 429.
        from app.curriculum.rate_limiter import rate_limiter
        rate_limiter.requests.clear()
        rate_limiter.blocked.clear()

        for _ in range(3):
            response = admin_client.post(
                '/admin/system/database/init',
                data={'confirm': INIT_DATABASE_CONFIRM},
                follow_redirects=False,
            )
            assert response.status_code == 302
        response = admin_client.post(
            '/admin/system/database/init',
            data={'confirm': INIT_DATABASE_CONFIRM},
            follow_redirects=False,
        )
        assert response.status_code == 429
        # Cleanup so other tests aren't affected
        rate_limiter.requests.clear()
        rate_limiter.blocked.clear()


class TestTestDbConnection:
    """Tests for test_db_connection route"""

    @patch('app.admin.routes.system_routes.SystemService.test_database_connection')
    def test_db_connection_success(self, mock_test_conn, admin_client, mock_admin_user):
        mock_test_conn.return_value = {
            'status': 'connected',
            'message': 'Connection successful'
        }
        response = admin_client.get('/admin/system/database/test-connection')
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['status'] == 'connected'
        mock_test_conn.assert_called_once()

    @patch('app.admin.routes.system_routes.SystemService.test_database_connection')
    def test_db_connection_error(self, mock_test_conn, admin_client, mock_admin_user):
        mock_test_conn.side_effect = Exception("Connection failed")
        response = admin_client.get('/admin/system/database/test-connection')
        assert response.status_code == 500
        json_data = response.get_json()
        assert json_data['status'] == 'error'
        assert 'Connection failed' in json_data['message']

    def test_db_connection_requires_admin(self, client):
        response = client.get('/admin/system/database/test-connection')
        assert response.status_code == 302


class TestMaskDatabaseUri:
    """Verify connection-string masking strips credentials."""

    def test_masks_postgres_credentials(self):
        uri = 'postgresql://user:secretpw@dbhost.local:5432/mydb?sslmode=require'
        masked = mask_database_uri(uri)
        assert 'secretpw' not in masked
        assert 'user' not in masked
        assert 'dbhost.local' in masked
        assert 'mydb' in masked

    def test_masks_postgres_with_driver(self):
        uri = 'postgresql+psycopg2://user:pw@host/dbname'
        masked = mask_database_uri(uri)
        assert masked == 'postgresql://host/dbname'

    def test_sqlite_compact(self):
        uri = 'sqlite:////var/data/app.db'
        assert mask_database_uri(uri) == 'sqlite'

    def test_empty_or_none(self):
        assert mask_database_uri('') == 'unknown'
        assert mask_database_uri(None) == 'unknown'  # type: ignore[arg-type]

    def test_malformed_url(self):
        # parser should not crash even on garbage input
        result = mask_database_uri('not a url')
        assert 'pw' not in result.lower()
        assert 'password' not in result.lower()


class TestSanitizeDbVersion:
    """Verify DB version banner is reduced to a short identifier."""

    def test_postgres_short(self):
        v = 'PostgreSQL 16.0 on x86_64-pc-linux-gnu, compiled by gcc 11.4.0, 64-bit'
        assert sanitize_db_version(v) == 'PostgreSQL 16.0'

    def test_no_match_returns_first_segment(self):
        assert sanitize_db_version('FooBar') == 'FooBar'

    def test_empty(self):
        assert sanitize_db_version('') == 'unknown'


class TestClearCacheAuditLog:
    """Verify clear_cache and clear_cache_prefix write to the audit log."""

    @patch('app.admin.routes.system_routes.log_admin_action')
    @patch('app.admin.routes.system_routes.clear_admin_cache')
    def test_clear_cache_calls_audit_log(self, mock_clear, mock_audit, admin_client, mock_admin_user):
        admin_client.post(
            '/admin/system/clear-cache',
            data={'confirm': CLEAR_CACHE_CONFIRM},
        )
        mock_audit.assert_called_once()
        action = mock_audit.call_args[0][1]
        assert 'cache' in action

    @patch('app.admin.routes.system_routes.log_admin_action')
    @patch('app.admin.routes.system_routes.clear_admin_cache')
    def test_clear_cache_no_audit_on_missing_confirm(self, mock_clear, mock_audit, admin_client, mock_admin_user):
        admin_client.post('/admin/system/clear-cache')
        mock_audit.assert_not_called()


class TestClearCachePrefix:
    """Tests for clear_cache_prefix route."""

    @patch('app.admin.routes.system_routes.clear_cache_by_prefix')
    def test_clear_prefix_success(self, mock_clear, admin_client, mock_admin_user):
        mock_clear.return_value = 3
        response = admin_client.post(
            '/admin/system/clear-cache-prefix',
            data={'prefix': 'seo_'},
            follow_redirects=False,
        )
        assert response.status_code == 302
        mock_clear.assert_called_once_with('seo_')

    @patch('app.admin.routes.system_routes.clear_cache_by_prefix')
    def test_clear_prefix_rejects_empty_prefix(self, mock_clear, admin_client, mock_admin_user):
        response = admin_client.post(
            '/admin/system/clear-cache-prefix',
            data={'prefix': ''},
            follow_redirects=False,
        )
        assert response.status_code == 302
        mock_clear.assert_not_called()

    @patch('app.admin.routes.system_routes.log_admin_action')
    @patch('app.admin.routes.system_routes.clear_cache_by_prefix')
    def test_clear_prefix_calls_audit_log(self, mock_clear, mock_audit, admin_client, mock_admin_user):
        mock_clear.return_value = 2
        admin_client.post(
            '/admin/system/clear-cache-prefix',
            data={'prefix': 'leaderboard'},
        )
        mock_audit.assert_called_once()
        action = mock_audit.call_args[0][1]
        assert 'cache' in action

    def test_clear_prefix_requires_admin(self, client):
        response = client.post(
            '/admin/system/clear-cache-prefix',
            data={'prefix': 'seo_'},
        )
        assert response.status_code == 302


class TestCachePrefixUnit:
    """Unit tests for clear_cache_by_prefix helper."""

    def test_prefix_removes_matching_keys(self):
        from app.admin.utils.cache import _cache, set_cache, clear_cache_by_prefix
        _cache.clear()
        set_cache('prefix_a', 1)
        set_cache('prefix_b', 2)
        set_cache('other_key', 3)

        removed = clear_cache_by_prefix('prefix_')
        assert removed == 2
        assert 'other_key' in _cache
        assert 'prefix_a' not in _cache
        assert 'prefix_b' not in _cache
        _cache.clear()

    def test_prefix_no_match_returns_zero(self):
        from app.admin.utils.cache import _cache, set_cache, clear_cache_by_prefix
        _cache.clear()
        set_cache('key1', 1)
        removed = clear_cache_by_prefix('nonexistent_')
        assert removed == 0
        _cache.clear()


class TestSystemInfoConfigLeak:
    """Make sure the rendered system info never exposes credentials."""

    def test_app_info_database_url_is_masked(self, app, admin_client, mock_admin_user):
        # Force a config URI with credentials.
        with app.app_context():
            original = app.config.get('SQLALCHEMY_DATABASE_URI')
            app.config['SQLALCHEMY_DATABASE_URI'] = (
                'postgresql://admin:s3cret@db.internal:5432/prod'
            )
            try:
                from app.admin.services.system_service import SystemService
                info = SystemService.get_system_info()
                assert 'error' not in info
                masked = info['app_info']['database_url']
                assert 's3cret' not in masked
                assert 'admin' not in masked.split('://')[1].split('/')[0]
            finally:
                if original is not None:
                    app.config['SQLALCHEMY_DATABASE_URI'] = original
