"""
Comprehensive tests for app/admin/routes/system_routes.py
Tests for system management, cache clearing, and database operations
"""
import pytest
from unittest.mock import patch, MagicMock
from flask import url_for


class TestClearCache:
    """Tests for clear_cache route"""

    @patch('app.admin.routes.system_routes.clear_admin_cache')
    def test_clear_cache_success(self, mock_clear_cache, admin_client, mock_admin_user):
        """Test successful cache clearing"""
        # Execute
        response = admin_client.post('/admin/system/clear-cache', follow_redirects=False)

        # Assert
        assert response.status_code == 302  # Redirect
        assert response.location.endswith('/admin/system')
        mock_clear_cache.assert_called_once()

    @patch('app.admin.routes.system_routes.clear_admin_cache')
    def test_clear_cache_error(self, mock_clear_cache, admin_client, mock_admin_user):
        """Test cache clearing with error"""
        mock_clear_cache.side_effect = Exception("Cache error")

        # Execute
        response = admin_client.post('/admin/system/clear-cache', follow_redirects=False)

        # Assert
        assert response.status_code == 302  # Still redirects
        mock_clear_cache.assert_called_once()

    def test_clear_cache_requires_admin(self, client):
        """Test that clear cache requires admin authentication"""
        response = client.post('/admin/system/clear-cache')
        assert response.status_code == 302  # Redirect to login


class TestSystemInfo:
    """Tests for system info route"""

    @patch('app.admin.routes.system_routes.render_template')
    @patch('app.admin.routes.system_routes.SystemService.get_system_info')
    def test_system_info_success(self, mock_get_info, mock_render, admin_client, mock_admin_user):
        """Test successful system info retrieval"""
        # Setup
        mock_get_info.return_value = {
            'system_info': {'os': 'Linux', 'python': '3.9'},
            'db_stats': {'tables': 10},
            'app_info': {'version': '1.0'}
        }

        # Mock render_template to avoid template rendering issues
        mock_render.return_value = '<html>system info</html>'

        # Execute
        response = admin_client.get('/admin/system')

        # Assert
        assert response.status_code == 200
        mock_get_info.assert_called_once()
        mock_render.assert_called_once()

    @patch('app.admin.routes.system_routes.SystemService.get_system_info')
    def test_system_info_error(self, mock_get_info, admin_client, mock_admin_user):
        """Test system info with error"""
        # Setup
        mock_get_info.return_value = {'error': 'System error'}

        # Execute
        response = admin_client.get('/admin/system', follow_redirects=False)

        # Assert
        assert response.status_code == 302  # Redirects to dashboard
        mock_get_info.assert_called_once()

    def test_system_info_requires_admin(self, client):
        """Test that system info requires admin authentication"""
        response = client.get('/admin/system')
        assert response.status_code == 302  # Redirect to login


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
        """Test successful database management page"""
        # Setup
        mock_test_conn.return_value = {'status': 'connected'}
        mock_word_stats.return_value = {'total': 1000}
        mock_book_stats.return_value = {'books': 50}
        mock_recent_ops.return_value = [{'op': 'insert', 'table': 'users'}]

        # Mock render_template to avoid template rendering issues
        mock_render.return_value = '<html>database management</html>'

        # Execute
        response = admin_client.get('/admin/system/database')

        # Assert
        assert response.status_code == 200
        mock_test_conn.assert_called_once()
        mock_word_stats.assert_called_once()
        mock_book_stats.assert_called_once()
        mock_recent_ops.assert_called_once()
        mock_render.assert_called_once()

    @patch('app.admin.routes.system_routes.SystemService.test_database_connection')
    def test_database_management_error(
        self,
        mock_test_conn,
        admin_client,
        mock_admin_user
    ):
        """Test database management with error"""
        # Setup
        mock_test_conn.side_effect = Exception("DB connection failed")

        # Execute
        response = admin_client.get('/admin/system/database')

        # Assert
        assert response.status_code == 200  # Still renders page with error
        mock_test_conn.assert_called_once()

    def test_database_management_requires_admin(self, client):
        """Test that database management requires admin authentication"""
        response = client.get('/admin/system/database')
        assert response.status_code == 302  # Redirect to login


class TestInitDatabase:
    """Tests for init_database route"""

    @patch('app.utils.db_init.init_db')
    def test_init_database_success(self, mock_init_db, admin_client, mock_admin_user):
        """Test successful database initialization"""
        # Execute
        response = admin_client.post('/admin/system/database/init', follow_redirects=False)

        # Assert
        assert response.status_code == 302  # Redirect
        assert response.location.endswith('/admin/system/database')
        mock_init_db.assert_called_once()

    @patch('app.utils.db_init.init_db')
    def test_init_database_error(self, mock_init_db, admin_client, mock_admin_user):
        """Test database initialization with error"""
        mock_init_db.side_effect = Exception("Init failed")

        # Execute
        response = admin_client.post('/admin/system/database/init', follow_redirects=False)

        # Assert
        assert response.status_code == 302  # Still redirects
        mock_init_db.assert_called_once()

    def test_init_database_requires_admin(self, client):
        """Test that init database requires admin authentication"""
        response = client.post('/admin/system/database/init')
        assert response.status_code == 302  # Redirect to login


class TestTestDbConnection:
    """Tests for test_db_connection route"""

    @patch('app.admin.routes.system_routes.SystemService.test_database_connection')
    def test_db_connection_success(self, mock_test_conn, admin_client, mock_admin_user):
        """Test successful database connection test"""
        # Setup
        mock_test_conn.return_value = {
            'status': 'connected',
            'message': 'Connection successful'
        }

        # Execute
        response = admin_client.get('/admin/system/database/test-connection')

        # Assert
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['status'] == 'connected'
        mock_test_conn.assert_called_once()

    @patch('app.admin.routes.system_routes.SystemService.test_database_connection')
    def test_db_connection_error(self, mock_test_conn, admin_client, mock_admin_user):
        """Test database connection test with error"""
        # Setup
        mock_test_conn.side_effect = Exception("Connection failed")

        # Execute
        response = admin_client.get('/admin/system/database/test-connection')

        # Assert
        assert response.status_code == 500
        json_data = response.get_json()
        assert json_data['status'] == 'error'
        assert 'Connection failed' in json_data['message']
        mock_test_conn.assert_called_once()

    def test_db_connection_requires_admin(self, client):
        """Test that db connection test requires admin authentication"""
        response = client.get('/admin/system/database/test-connection')
        assert response.status_code == 302  # Redirect to login