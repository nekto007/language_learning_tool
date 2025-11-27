"""
Comprehensive tests for app/admin/routes/curriculum_routes.py
Tests for curriculum management routes (261 lines)
Target: Increase coverage to help reach 55% overall project coverage
"""
import pytest
import json
from unittest.mock import patch, MagicMock, mock_open
from io import BytesIO


class TestCurriculumIndex:
    """Tests for curriculum() route"""

    @patch('app.admin.routes.curriculum_routes.render_template')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.Lessons')
    @patch('app.admin.routes.curriculum_routes.db.session')
    def test_curriculum_index_success(self, mock_session, mock_lessons, mock_level, mock_render, admin_client, mock_admin_user):
        """Test successful curriculum index page"""
        # Setup mocks
        mock_level.query.order_by.return_value.all.return_value = []
        mock_lessons.query.order_by.return_value.limit.return_value.all.return_value = []
        mock_session.query.return_value.scalar.return_value = 5

        # Mock render_template to avoid cache serialization
        mock_render.return_value = '<html>curriculum index</html>'

        # Execute
        response = admin_client.get('/admin/curriculum')

        # Assert
        assert response.status_code == 200
        mock_level.query.order_by.assert_called_once()
        mock_lessons.query.order_by.assert_called_once()
        mock_render.assert_called_once()

    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    def test_curriculum_index_error(self, mock_level, admin_client, mock_admin_user):
        """Test curriculum index with database error"""
        mock_level.query.order_by.side_effect = Exception("Database error")

        # The route doesn't have error handling, so exception propagates
        with pytest.raises(Exception, match="Database error"):
            admin_client.get('/admin/curriculum')

    def test_curriculum_index_requires_admin(self, client):
        """Test that curriculum index requires admin authentication"""
        response = client.get('/admin/curriculum')
        assert response.status_code == 302


class TestLevelList:
    """Tests for level_list() route"""

    @patch('app.admin.routes.curriculum_routes.render_template')
    @patch('app.admin.routes.curriculum_routes.Module')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.db.session')
    def test_level_list_success(self, mock_session, mock_level, mock_module, mock_render, admin_client, mock_admin_user):
        """Test successful level list page"""
        # Setup mock level
        mock_level_obj = MagicMock()
        mock_level_obj.id = 1
        mock_level.query.order_by.return_value.all.return_value = [mock_level_obj]

        # Setup module count
        mock_module.query.filter_by.return_value.count.return_value = 10

        # Setup lesson count
        mock_session.query.return_value.join.return_value.filter.return_value.count.return_value = 50

        # Mock render_template to avoid cache serialization
        mock_render.return_value = '<html>level list</html>'

        # Execute
        response = admin_client.get('/admin/curriculum/levels')

        # Assert
        assert response.status_code == 200
        mock_level.query.order_by.assert_called_once()
        mock_render.assert_called_once()

    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    def test_level_list_empty(self, mock_level, admin_client, mock_admin_user):
        """Test level list with no levels"""
        mock_level.query.order_by.return_value.all.return_value = []

        response = admin_client.get('/admin/curriculum/levels')

        assert response.status_code == 200

    def test_level_list_requires_admin(self, client):
        """Test that level list requires admin authentication"""
        response = client.get('/admin/curriculum/levels')
        assert response.status_code == 302


class TestModuleList:
    """Tests for module_list() route"""

    @patch('app.admin.routes.curriculum_routes.Lessons')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.Module')
    def test_module_list_all(self, mock_module, mock_level, mock_lessons, admin_client, mock_admin_user):
        """Test module list without level filter"""
        # Setup mocks
        mock_module_obj = MagicMock()
        mock_module_obj.id = 1
        mock_module.query.join.return_value.order_by.return_value.all.return_value = [mock_module_obj]

        mock_lessons.query.filter_by.return_value.count.return_value = 5

        mock_level.query.order_by.return_value.all.return_value = []

        # Execute
        response = admin_client.get('/admin/curriculum/modules')

        # Assert
        assert response.status_code == 200

    @patch('app.admin.routes.curriculum_routes.Lessons')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.Module')
    def test_module_list_filtered(self, mock_module, mock_level, mock_lessons, admin_client, mock_admin_user):
        """Test module list with level filter"""
        # Setup mocks
        mock_module_obj = MagicMock()
        mock_module.query.join.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_module_obj]

        mock_lessons.query.filter_by.return_value.count.return_value = 3

        mock_level.query.order_by.return_value.all.return_value = []

        # Execute
        response = admin_client.get('/admin/curriculum/modules?level_id=1')

        # Assert
        assert response.status_code == 200

    def test_module_list_requires_admin(self, client):
        """Test that module list requires admin authentication"""
        response = client.get('/admin/curriculum/modules')
        assert response.status_code == 302


class TestLessonList:
    """Tests for lesson_list() route"""

    @patch('app.admin.routes.curriculum_routes.Module')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.Lessons')
    def test_lesson_list_all(self, mock_lessons, mock_level, mock_module, admin_client, mock_admin_user):
        """Test lesson list without filters"""
        # Setup mocks
        mock_lessons.query.join.return_value.join.return_value.order_by.return_value.all.return_value = []
        mock_level.query.order_by.return_value.all.return_value = []
        mock_module.query.join.return_value.order_by.return_value.all.return_value = []

        # Execute
        response = admin_client.get('/admin/curriculum/lessons')

        # Assert
        assert response.status_code == 200

    @patch('app.admin.routes.curriculum_routes.Module')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.Lessons')
    def test_lesson_list_with_level_filter(self, mock_lessons, mock_level, mock_module, admin_client, mock_admin_user):
        """Test lesson list with level filter"""
        # Setup mocks
        mock_query = MagicMock()
        mock_lessons.query.join.return_value.join.return_value = mock_query
        mock_query.filter.return_value.order_by.return_value.all.return_value = []

        mock_level.query.order_by.return_value.all.return_value = []
        mock_module.query.filter_by.return_value.order_by.return_value.all.return_value = []

        # Execute
        response = admin_client.get('/admin/curriculum/lessons?level_id=1')

        # Assert
        assert response.status_code == 200

    @patch('app.admin.routes.curriculum_routes.Module')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.Lessons')
    def test_lesson_list_with_module_filter(self, mock_lessons, mock_level, mock_module, admin_client, mock_admin_user):
        """Test lesson list with module filter"""
        # Setup mocks
        mock_query = MagicMock()
        mock_lessons.query.join.return_value.join.return_value = mock_query
        mock_query.filter.return_value.order_by.return_value.all.return_value = []

        mock_level.query.order_by.return_value.all.return_value = []
        mock_module.query.join.return_value.order_by.return_value.all.return_value = []

        # Execute
        response = admin_client.get('/admin/curriculum/lessons?module_id=5')

        # Assert
        assert response.status_code == 200

    @patch('app.admin.routes.curriculum_routes.Module')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.Lessons')
    def test_lesson_list_with_search(self, mock_lessons, mock_level, mock_module, admin_client, mock_admin_user):
        """Test lesson list with search query"""
        # Setup mocks
        mock_query = MagicMock()
        mock_lessons.query.join.return_value.join.return_value = mock_query
        mock_query.filter.return_value.order_by.return_value.all.return_value = []

        mock_level.query.order_by.return_value.all.return_value = []
        mock_module.query.join.return_value.order_by.return_value.all.return_value = []

        # Execute
        response = admin_client.get('/admin/curriculum/lessons?search=grammar')

        # Assert
        assert response.status_code == 200

    def test_lesson_list_requires_admin(self, client):
        """Test that lesson list requires admin authentication"""
        response = client.get('/admin/curriculum/lessons')
        assert response.status_code == 302


class TestUserProgress:
    """Tests for user_progress() route"""

    @patch('app.admin.routes.curriculum_routes.render_template')
    @patch('app.admin.routes.curriculum_routes.User')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.db.session')
    def test_user_progress_all(self, mock_session, mock_level, mock_user, mock_render, admin_client, mock_admin_user):
        """Test user progress without filters"""
        # Setup complex query mock
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.order_by.return_value.all.return_value = []

        # Status counts
        mock_session.query.return_value.group_by.return_value.all.return_value = [
            ('completed', 10),
            ('in_progress', 5)
        ]

        mock_user.query.order_by.return_value.all.return_value = []
        mock_level.query.order_by.return_value.all.return_value = []

        # Mock render_template to avoid cache serialization
        mock_render.return_value = '<html>user progress</html>'

        # Execute
        response = admin_client.get('/admin/curriculum/progress')

        # Assert
        assert response.status_code == 200
        mock_render.assert_called_once()

    @patch('app.admin.routes.curriculum_routes.render_template')
    @patch('app.admin.routes.curriculum_routes.Module')
    @patch('app.admin.routes.curriculum_routes.User')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.db.session')
    def test_user_progress_with_user_filter(self, mock_session, mock_level, mock_user, mock_module, mock_render, admin_client, mock_admin_user):
        """Test user progress with user filter"""
        # Setup complex query mock
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.all.return_value = []

        # Status counts
        mock_session.query.return_value.group_by.return_value.all.return_value = []

        mock_user.query.order_by.return_value.all.return_value = []
        mock_level.query.order_by.return_value.all.return_value = []

        # Mock render_template to avoid cache serialization
        mock_render.return_value = '<html>user progress filtered</html>'

        # Execute
        response = admin_client.get('/admin/curriculum/progress?user_id=1')

        # Assert
        assert response.status_code == 200
        mock_render.assert_called_once()

    @patch('app.admin.routes.curriculum_routes.render_template')
    @patch('app.admin.routes.curriculum_routes.Module')
    @patch('app.admin.routes.curriculum_routes.User')
    @patch('app.admin.routes.curriculum_routes.CEFRLevel')
    @patch('app.admin.routes.curriculum_routes.db.session')
    def test_user_progress_with_level_filter(self, mock_session, mock_level, mock_user, mock_module, mock_render, admin_client, mock_admin_user):
        """Test user progress with level filter"""
        # Setup complex query mock
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.join.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.all.return_value = []

        # Status counts
        mock_session.query.return_value.group_by.return_value.all.return_value = []

        mock_user.query.order_by.return_value.all.return_value = []
        mock_level.query.order_by.return_value.all.return_value = []
        mock_module.query.filter_by.return_value.order_by.return_value.all.return_value = []

        # Mock render_template to avoid cache serialization
        mock_render.return_value = '<html>user progress level</html>'

        # Execute
        response = admin_client.get('/admin/curriculum/progress?level_id=2')

        # Assert
        assert response.status_code == 200
        mock_render.assert_called_once()

    def test_user_progress_requires_admin(self, client):
        """Test that user progress requires admin authentication"""
        response = client.get('/admin/curriculum/progress')
        assert response.status_code == 302


class TestImportCurriculum:
    """Tests for import_curriculum() route"""

    def test_import_get(self, admin_client, mock_admin_user):
        """Test GET import curriculum page"""
        response = admin_client.get('/admin/curriculum/import')

        assert response.status_code == 200

    @patch('app.admin.routes.curriculum_routes.CurriculumImportService.import_curriculum_data')
    @patch('app.admin.routes.curriculum_routes.Module')
    def test_import_post_with_json_text(self, mock_module, mock_import, admin_client, mock_admin_user):
        """Test POST import with JSON text"""
        # Setup mock
        mock_import.return_value = {
            'lesson_id': 123,
            'module_id': 5
        }

        mock_module_obj = MagicMock()
        mock_module_obj.id = 5
        mock_module.query.get.return_value = mock_module_obj

        # Prepare JSON data
        json_text = json.dumps({
            'module': {
                'title': 'Test Module',
                'lessons': []
            }
        })

        # Execute
        response = admin_client.post(
            '/admin/curriculum/import',
            data={'json_text': json_text},
            follow_redirects=False
        )

        # Assert
        assert response.status_code == 302
        mock_import.assert_called_once()

    @patch('app.utils.file_security.validate_text_file_upload')
    @patch('app.admin.routes.curriculum_routes.CurriculumImportService.import_curriculum_data')
    @patch('app.admin.routes.curriculum_routes.Module')
    def test_import_post_with_file(self, mock_module, mock_import, mock_validate, admin_client, mock_admin_user):
        """Test POST import with JSON file"""
        # Setup validation
        mock_validate.return_value = (True, None)

        # Setup import
        mock_import.return_value = {
            'lesson_id': 456,
            'module_id': 3
        }

        mock_module.query.get.return_value = None

        # Prepare file
        json_data = json.dumps({
            'module': {
                'title': 'Test Module',
                'lessons': []
            }
        })
        file_data = BytesIO(json_data.encode('utf-8'))

        # Execute
        response = admin_client.post(
            '/admin/curriculum/import',
            data={
                'json_file': (file_data, 'test.json')
            },
            content_type='multipart/form-data',
            follow_redirects=False
        )

        # Assert
        assert response.status_code == 302
        mock_validate.assert_called_once()
        mock_import.assert_called_once()

    def test_import_post_invalid_json_text(self, admin_client, mock_admin_user):
        """Test POST import with invalid JSON text"""
        response = admin_client.post(
            '/admin/curriculum/import',
            data={'json_text': 'invalid json{'},
            follow_redirects=False
        )

        assert response.status_code == 302
        assert response.location.endswith('/admin/curriculum/import')

    @patch('app.utils.file_security.validate_text_file_upload')
    def test_import_post_invalid_file(self, mock_validate, admin_client, mock_admin_user):
        """Test POST import with invalid file"""
        # Setup validation failure
        mock_validate.return_value = (False, 'File too large')

        # Prepare file
        file_data = BytesIO(b'some data')

        # Execute
        response = admin_client.post(
            '/admin/curriculum/import',
            data={
                'json_file': (file_data, 'test.json')
            },
            content_type='multipart/form-data',
            follow_redirects=False
        )

        # Assert
        assert response.status_code == 302
        mock_validate.assert_called_once()

    @patch('app.admin.routes.curriculum_routes.CurriculumImportService.import_curriculum_data')
    def test_import_post_service_error(self, mock_import, admin_client, mock_admin_user):
        """Test POST import with service error"""
        # Setup import to fail
        mock_import.side_effect = Exception("Import failed")

        json_text = json.dumps({'module': {}})

        # Execute
        response = admin_client.post(
            '/admin/curriculum/import',
            data={'json_text': json_text},
            follow_redirects=False
        )

        # Assert
        assert response.status_code == 302
        assert response.location.endswith('/admin/curriculum/import')

    def test_import_requires_admin(self, client):
        """Test that import requires admin authentication"""
        response = client.get('/admin/curriculum/import')
        assert response.status_code == 302

        response = client.post('/admin/curriculum/import')
        assert response.status_code == 302