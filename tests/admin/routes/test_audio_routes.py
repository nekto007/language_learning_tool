"""
Comprehensive tests for app/admin/routes/audio_routes.py
Tests for audio management routes (169 lines)
Target: Increase coverage to help reach 55% overall project coverage
"""
import pytest
from unittest.mock import patch, MagicMock


class TestAudioManagement:
    """Tests for audio_management() route"""

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_audio_statistics')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    def test_audio_management_success(self, mock_get_stats, admin_client, mock_admin_user):
        """Test successful audio management page"""
        # Setup mock
        mock_get_stats.return_value = {
            'words_total': 1000,
            'words_with_audio': 800,
            'words_without_audio': 200,
            'problematic_audio': 10,
            'recent_audio_updates': [],
            'media_folder': '/media'
        }

        # Execute
        response = admin_client.get('/admin/audio')

        # Assert
        assert response.status_code == 200
        mock_get_stats.assert_called_once()

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_audio_statistics')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    def test_audio_management_with_error(self, mock_get_stats, admin_client, mock_admin_user):
        """Test audio management with error in stats"""
        # Setup mock to return error
        mock_get_stats.return_value = {'error': 'Database error'}

        # Execute
        response = admin_client.get('/admin/audio', follow_redirects=False)

        # Assert - should redirect to dashboard
        assert response.status_code == 302
        assert '/admin/' in response.location

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_audio_statistics')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    def test_audio_management_exception(self, mock_get_stats, admin_client, mock_admin_user):
        """Test audio management with exception"""
        # Setup mock to raise exception
        mock_get_stats.side_effect = Exception("Service error")

        # Execute
        response = admin_client.get('/admin/audio', follow_redirects=False)

        # Assert - should redirect to dashboard
        assert response.status_code == 302

    def test_audio_management_requires_admin(self, client):
        """Test that audio management requires admin authentication"""
        response = client.get('/admin/audio')
        assert response.status_code == 302


class TestUpdateAudioDownloadStatus:
    """Tests for update_audio_download_status() route"""

    @patch('app.admin.routes.audio_routes.AudioManagementService.update_download_status')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    @patch('config.settings.COLLECTIONS_TABLE', 'collection_words')
    def test_update_download_status_success(self, mock_update, admin_client, mock_admin_user):
        """Test successful audio download status update"""
        # Setup mock
        mock_update.return_value = 50

        # Execute
        response = admin_client.post(
            '/admin/audio/update-download-status',
            json={'table': 'collection_words'}
        )

        # Assert
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['updated_count'] == 50
        mock_update.assert_called_once()

    @patch('app.admin.routes.audio_routes.AudioManagementService.update_download_status')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    @patch('config.settings.COLLECTIONS_TABLE', 'collection_words')
    def test_update_download_status_default_table(self, mock_update, admin_client, mock_admin_user):
        """Test update status with default table"""
        # Setup mock
        mock_update.return_value = 30

        # Execute
        response = admin_client.post(
            '/admin/audio/update-download-status',
            json={}
        )

        # Assert
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['table_name'] == 'collection_words'

    @patch('app.admin.routes.audio_routes.AudioManagementService.update_download_status')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    @patch('config.settings.COLLECTIONS_TABLE', 'collection_words')
    def test_update_download_status_phrasal_verbs(self, mock_update, admin_client, mock_admin_user):
        """Test update status with phrasal verbs table"""
        # Setup mock
        mock_update.return_value = 10

        # Execute
        response = admin_client.post(
            '/admin/audio/update-download-status',
            json={'table': 'phrasal_verbs'}
        )

        # Assert
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True

    @patch('app.admin.routes.audio_routes.AudioManagementService.update_download_status')
    @patch('config.settings.MEDIA_FOLDER', '/media')
    @patch('config.settings.COLLECTIONS_TABLE', 'collection_words')
    def test_update_download_status_error(self, mock_update, admin_client, mock_admin_user):
        """Test update status with error"""
        # Setup mock to raise exception
        mock_update.side_effect = Exception("Update failed")

        # Execute
        response = admin_client.post(
            '/admin/audio/update-download-status',
            json={'table': 'collection_words'}
        )

        # Assert
        assert response.status_code == 500
        json_data = response.get_json()
        assert json_data['success'] is False

    def test_update_download_status_requires_admin(self, client):
        """Test that update download status requires admin authentication"""
        response = client.post('/admin/audio/update-download-status', json={})
        assert response.status_code == 302


class TestFixAudioListeningFields:
    """Tests for fix_audio_listening_fields() route"""

    @patch('app.admin.routes.audio_routes.clear_admin_cache')
    @patch('app.admin.routes.audio_routes.AudioManagementService.fix_listening_fields')
    def test_fix_listening_fields_success(self, mock_fix, mock_cache, admin_client, mock_admin_user):
        """Test successful listening fields fix"""
        # Setup mock
        mock_fix.return_value = (True, 25, 'Fixed 25 records')

        # Execute
        response = admin_client.post('/admin/audio/fix-listening-fields')

        # Assert
        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['fixed_count'] == 25
        mock_cache.assert_called_once()

    @patch('app.admin.routes.audio_routes.AudioManagementService.fix_listening_fields')
    def test_fix_listening_fields_failure(self, mock_fix, admin_client, mock_admin_user):
        """Test listening fields fix with service failure"""
        # Setup mock to return failure
        mock_fix.return_value = (False, 0, 'Fix failed')

        # Execute
        response = admin_client.post('/admin/audio/fix-listening-fields')

        # Assert
        assert response.status_code == 500
        json_data = response.get_json()
        assert json_data['success'] is False

    @patch('app.admin.routes.audio_routes.AudioManagementService.fix_listening_fields')
    def test_fix_listening_fields_exception(self, mock_fix, admin_client, mock_admin_user):
        """Test listening fields fix with exception"""
        # Setup mock to raise exception
        mock_fix.side_effect = Exception("Service error")

        # Execute
        response = admin_client.post('/admin/audio/fix-listening-fields')

        # Assert
        assert response.status_code == 500
        json_data = response.get_json()
        assert json_data['success'] is False

    def test_fix_listening_fields_requires_admin(self, client):
        """Test that fix listening fields requires admin authentication"""
        response = client.post('/admin/audio/fix-listening-fields')
        assert response.status_code == 302


class TestGetAudioDownloadList:
    """Tests for get_audio_download_list() route"""

    @patch('app.admin.routes.audio_routes.export_audio_list_txt')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_txt(self, mock_get_list, mock_export, admin_client, mock_admin_user):
        """Test download list in TXT format"""
        # Setup mocks
        mock_get_list.return_value = ['word1', 'word2', 'word3']
        mock_export.return_value = 'text file response'

        # Execute
        response = admin_client.get('/admin/audio/get-download-list?format=txt')

        # Assert
        assert response.status_code == 200
        mock_get_list.assert_called_once_with(None)
        mock_export.assert_called_once()

    @patch('app.admin.routes.audio_routes.export_audio_list_json')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_json(self, mock_get_list, mock_export, admin_client, mock_admin_user):
        """Test download list in JSON format"""
        # Setup mocks
        mock_get_list.return_value = ['word1', 'word2']
        mock_export.return_value = 'json response'

        # Execute
        response = admin_client.get('/admin/audio/get-download-list?format=json')

        # Assert
        assert response.status_code == 200
        mock_export.assert_called_once()

    @patch('app.admin.routes.audio_routes.export_audio_list_csv')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_csv(self, mock_get_list, mock_export, admin_client, mock_admin_user):
        """Test download list in CSV format"""
        # Setup mocks
        mock_get_list.return_value = ['word1']
        mock_export.return_value = 'csv response'

        # Execute
        response = admin_client.get('/admin/audio/get-download-list?format=csv')

        # Assert
        assert response.status_code == 200
        mock_export.assert_called_once()

    @patch('app.admin.routes.audio_routes.export_audio_list_txt')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_with_pattern(self, mock_get_list, mock_export, admin_client, mock_admin_user):
        """Test download list with pattern filter"""
        # Setup mocks
        mock_get_list.return_value = ['apple', 'application']
        mock_export.return_value = 'filtered response'

        # Execute
        response = admin_client.get('/admin/audio/get-download-list?pattern=app')

        # Assert
        assert response.status_code == 200
        mock_get_list.assert_called_once_with('app')

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_empty(self, mock_get_list, admin_client, mock_admin_user):
        """Test download list with no words"""
        # Setup mock to return empty list
        mock_get_list.return_value = []

        # Execute
        response = admin_client.get('/admin/audio/get-download-list', follow_redirects=False)

        # Assert - should redirect back to audio management
        assert response.status_code == 302
        assert 'audio' in response.location

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_download_list')
    def test_get_download_list_error(self, mock_get_list, admin_client, mock_admin_user):
        """Test download list with error"""
        # Setup mock to raise exception
        mock_get_list.side_effect = Exception("Service error")

        # Execute
        response = admin_client.get('/admin/audio/get-download-list', follow_redirects=False)

        # Assert - should redirect with error flash
        assert response.status_code == 302

    def test_get_download_list_requires_admin(self, client):
        """Test that get download list requires admin authentication"""
        response = client.get('/admin/audio/get-download-list')
        assert response.status_code == 302


class TestAudioStatistics:
    """Tests for audio_statistics() route"""

    @patch('app.admin.routes.audio_routes.render_template')
    @patch('app.admin.routes.audio_routes.AudioManagementService.get_detailed_statistics')
    def test_audio_statistics_success(self, mock_get_stats, mock_render, admin_client, mock_admin_user):
        """Test successful audio statistics page"""
        # Setup mock
        mock_get_stats.return_value = {
            'download_stats': {'total': 1000},
            'listening_stats': {'completed': 500},
            'level_audio_stats': {'A1': 200, 'A2': 300}
        }

        # Mock render_template to avoid template rendering issues
        mock_render.return_value = '<html>audio statistics</html>'

        # Execute
        response = admin_client.get('/admin/audio/statistics')

        # Assert
        assert response.status_code == 200
        mock_get_stats.assert_called_once()
        mock_render.assert_called_once()

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_detailed_statistics')
    def test_audio_statistics_with_error(self, mock_get_stats, admin_client, mock_admin_user):
        """Test audio statistics with error"""
        # Setup mock to return error
        mock_get_stats.return_value = {'error': 'Statistics error'}

        # Execute
        response = admin_client.get('/admin/audio/statistics', follow_redirects=False)

        # Assert - should redirect back to audio management
        assert response.status_code == 302
        assert 'audio' in response.location

    @patch('app.admin.routes.audio_routes.AudioManagementService.get_detailed_statistics')
    def test_audio_statistics_exception(self, mock_get_stats, admin_client, mock_admin_user):
        """Test audio statistics with exception"""
        # Setup mock to raise exception
        mock_get_stats.side_effect = Exception("Service error")

        # Execute
        response = admin_client.get('/admin/audio/statistics', follow_redirects=False)

        # Assert - should redirect with error flash
        assert response.status_code == 302

    def test_audio_statistics_requires_admin(self, client):
        """Test that audio statistics requires admin authentication"""
        response = client.get('/admin/audio/statistics')
        assert response.status_code == 302