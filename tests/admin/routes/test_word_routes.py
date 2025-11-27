"""
Tests for app/admin/routes/word_routes.py
5 routes, 246 lines, currently 22% coverage
Quick tests to boost coverage to 50%+
"""
import pytest
from unittest.mock import patch, MagicMock


class TestWordManagement:
    """Tests for word_management() route"""

    @patch('app.admin.routes.word_routes.WordManagementService.get_word_statistics')
    def test_word_management_success(self, mock_get_stats, admin_client, mock_admin_user):
        """Test successful word management page"""
        mock_get_stats.return_value = {
            'words_total': 1000,
            'status_stats': {},
            'recent_words': [],
            'words_without_translation': 50
        }

        response = admin_client.get('/admin/words')

        assert response.status_code == 200
        mock_get_stats.assert_called_once()

    @patch('app.admin.routes.word_routes.WordManagementService.get_word_statistics')
    def test_word_management_error(self, mock_get_stats, admin_client, mock_admin_user):
        """Test word management with error"""
        mock_get_stats.return_value = {'error': 'Database error'}

        response = admin_client.get('/admin/words', follow_redirects=False)

        assert response.status_code == 302

    def test_word_management_requires_admin(self, client):
        """Test authentication required"""
        response = client.get('/admin/words')
        assert response.status_code == 302


class TestBulkStatusUpdate:
    """Tests for bulk_status_update() route"""

    @patch('app.admin.routes.word_routes.clear_admin_cache')
    @patch('app.admin.routes.word_routes.WordManagementService.bulk_update_word_status')
    def test_bulk_status_update_post_success(self, mock_update, mock_cache, admin_client, mock_admin_user):
        """Test successful bulk status update"""
        mock_update.return_value = (True, 10, 10, None)

        response = admin_client.post(
            '/admin/words/bulk-status-update',
            json={'words': ['test', 'word'], 'status': 'active'}
        )

        assert response.status_code == 200
        json_data = response.get_json()
        assert json_data['success'] is True
        assert json_data['updated_count'] == 10
        mock_cache.assert_called_once()

    @patch('app.admin.routes.word_routes.WordManagementService.bulk_update_word_status')
    def test_bulk_status_update_validation_error(self, mock_update, admin_client, mock_admin_user):
        """Test bulk update with validation error"""
        mock_update.return_value = (False, 0, 0, 'Требуются words и status')

        response = admin_client.post(
            '/admin/words/bulk-status-update',
            json={}
        )

        assert response.status_code == 400

    def test_bulk_status_update_requires_admin(self, client):
        """Test authentication required"""
        response = client.post('/admin/words/bulk-status-update', json={})
        assert response.status_code == 302


class TestExportWords:
    """Tests for export_words() route"""

    @patch('app.admin.routes.word_routes.export_words_json')
    def test_export_words_json(self, mock_export, admin_client, mock_admin_user):
        """Test JSON export"""
        mock_export.return_value = MagicMock()

        response = admin_client.get('/admin/words/export?format=json')

        assert response.status_code == 200
        mock_export.assert_called_once()

    @patch('app.admin.routes.word_routes.export_words_csv')
    def test_export_words_csv(self, mock_export, admin_client, mock_admin_user):
        """Test CSV export"""
        mock_export.return_value = MagicMock()

        response = admin_client.get('/admin/words/export?format=csv')

        assert response.status_code == 200
        mock_export.assert_called_once()

    @patch('app.admin.routes.word_routes.export_words_txt')
    def test_export_words_txt(self, mock_export, admin_client, mock_admin_user):
        """Test TXT export"""
        mock_export.return_value = MagicMock()

        response = admin_client.get('/admin/words/export?format=txt')

        assert response.status_code == 200
        mock_export.assert_called_once()

    def test_export_words_requires_admin(self, client):
        """Test authentication required"""
        response = client.get('/admin/words/export')
        assert response.status_code == 302


class TestImportTranslations:
    """Tests for import_translations() route"""

    def test_import_translations_get(self, admin_client, mock_admin_user):
        """Test GET import translations page"""
        response = admin_client.get('/admin/words/import-translations')

        assert response.status_code == 200

    @patch('app.admin.routes.word_routes.save_import_data')
    @patch('app.admin.routes.word_routes.WordManagementService.import_translations')
    def test_import_translations_post_success(self, mock_import, mock_save, admin_client, mock_admin_user):
        """Test POST import translations"""
        mock_import.return_value = (True, 10, 'Success')

        response = admin_client.post(
            '/admin/words/import-translations',
            data={'data': 'test,тест'},
            follow_redirects=False
        )

        # May redirect or return 200 depending on form
        assert response.status_code in [200, 302]

    def test_import_translations_requires_admin(self, client):
        """Test authentication required"""
        response = client.get('/admin/words/import-translations')
        assert response.status_code == 302


class TestWordStatistics:
    """Tests for word_statistics() route"""

    @patch('app.admin.routes.word_routes.CollectionWords')
    def test_word_statistics_success(self, mock_words, admin_client, mock_admin_user):
        """Test successful word statistics page"""
        mock_words.query.count.return_value = 1000
        mock_words.query.filter_by.return_value.count.return_value = 900

        response = admin_client.get('/admin/words/statistics')

        assert response.status_code == 200

    def test_word_statistics_requires_admin(self, client):
        """Test authentication required"""
        response = client.get('/admin/words/statistics')
        assert response.status_code == 302