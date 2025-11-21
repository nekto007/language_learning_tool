# tests/admin/services/test_user_management_service.py

"""
Unit tests for UserManagementService
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta, UTC

from app.admin.services.user_management_service import UserManagementService


class TestUserManagementService:
    """Tests for UserManagementService"""

    @patch('app.admin.services.user_management_service.User')
    def test_get_all_users_success(self, mock_user):
        """Test successful retrieval of paginated users"""
        # Mock pagination object
        mock_pagination = Mock()
        mock_pagination.items = [
            Mock(id=1, username='user1', email='user1@test.com'),
            Mock(id=2, username='user2', email='user2@test.com')
        ]
        mock_pagination.total = 50
        mock_pagination.pages = 5

        mock_user.query.order_by.return_value.paginate.return_value = mock_pagination

        result = UserManagementService.get_all_users(page=1, per_page=10)

        assert result['total'] == 50
        assert result['pages'] == 5
        assert result['current_page'] == 1
        assert len(result['users']) == 2
        assert result['users'][0].username == 'user1'

    @patch('app.admin.services.user_management_service.User')
    def test_get_all_users_empty(self, mock_user):
        """Test getting users when database is empty"""
        mock_pagination = Mock()
        mock_pagination.items = []
        mock_pagination.total = 0
        mock_pagination.pages = 0

        mock_user.query.order_by.return_value.paginate.return_value = mock_pagination

        result = UserManagementService.get_all_users()

        assert result['total'] == 0
        assert result['pages'] == 0
        assert len(result['users']) == 0

    @patch('app.admin.services.user_management_service.db')
    @patch('app.admin.services.user_management_service.UserModule')
    @patch('app.admin.services.user_management_service.LessonProgress')
    @patch('app.admin.services.user_management_service.UserWord')
    @patch('app.admin.services.user_management_service.User')
    def test_get_user_statistics_success(self, mock_user, mock_userword,
                                         mock_lesson_progress, mock_user_module, mock_db):
        """Test successful retrieval of user statistics"""
        # Mock user
        mock_user_obj = Mock()
        mock_user_obj.id = 1
        mock_user_obj.username = 'testuser'
        mock_user_obj.email = 'test@test.com'
        mock_user_obj.created_at = datetime(2024, 1, 1)
        mock_user.query.get.return_value = mock_user_obj

        # Mock word statistics
        mock_db.session.query.return_value.filter.return_value.group_by.return_value.all.side_effect = [
            [('new', 10), ('learning', 20), ('review', 15), ('mastered', 5)],  # word stats
            [('not_started', 5), ('in_progress', 3), ('completed', 7)]  # lesson stats
        ]

        # Mock module count
        mock_user_module.query.filter_by.return_value.count.return_value = 3

        result = UserManagementService.get_user_statistics(1)

        assert result is not None
        assert result['user_id'] == 1
        assert result['username'] == 'testuser'
        assert result['email'] == 'test@test.com'
        assert result['words']['total'] == 50
        assert result['words']['new'] == 10
        assert result['words']['learning'] == 20
        assert result['words']['review'] == 15
        assert result['words']['mastered'] == 5
        assert result['lessons']['total'] == 15
        assert result['lessons']['not_started'] == 5
        assert result['lessons']['in_progress'] == 3
        assert result['lessons']['completed'] == 7
        assert result['modules_enabled'] == 3

    @patch('app.admin.services.user_management_service.User')
    def test_get_user_statistics_user_not_found(self, mock_user):
        """Test getting statistics for non-existent user"""
        mock_user.query.get.return_value = None

        result = UserManagementService.get_user_statistics(999)

        assert result is None

    @patch('app.admin.services.user_management_service.db')
    @patch('app.admin.services.user_management_service.UserModule')
    @patch('app.admin.services.user_management_service.LessonProgress')
    @patch('app.admin.services.user_management_service.UserWord')
    @patch('app.admin.services.user_management_service.User')
    def test_get_user_statistics_no_activity(self, mock_user, mock_userword,
                                             mock_lesson_progress, mock_user_module, mock_db):
        """Test statistics for user with no activity"""
        mock_user_obj = Mock()
        mock_user_obj.id = 1
        mock_user_obj.username = 'newuser'
        mock_user_obj.email = 'new@test.com'
        mock_user_obj.created_at = datetime(2024, 1, 1)
        mock_user.query.get.return_value = mock_user_obj

        # Mock empty statistics
        mock_db.session.query.return_value.filter.return_value.group_by.return_value.all.side_effect = [
            [],  # no word stats
            []   # no lesson stats
        ]
        mock_user_module.query.filter_by.return_value.count.return_value = 0

        result = UserManagementService.get_user_statistics(1)

        assert result['words']['total'] == 0
        assert result['lessons']['total'] == 0
        assert result['modules_enabled'] == 0

    @patch('app.admin.services.user_management_service.db')
    @patch('app.admin.services.user_management_service.UserModule')
    def test_toggle_module_access_existing(self, mock_user_module, mock_db):
        """Test toggling module access for existing module"""
        mock_module = Mock()
        mock_module.is_enabled = False
        mock_user_module.query.filter_by.return_value.first.return_value = mock_module

        result = UserManagementService.toggle_user_module_access(1, 'module_01', True)

        assert result is True
        assert mock_module.is_enabled is True
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.user_management_service.db')
    @patch('app.admin.services.user_management_service.UserModule')
    def test_toggle_module_access_new(self, mock_user_module, mock_db):
        """Test toggling module access for new module"""
        mock_user_module.query.filter_by.return_value.first.return_value = None

        result = UserManagementService.toggle_user_module_access(1, 'module_02', True)

        assert result is True
        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.user_management_service.db')
    @patch('app.admin.services.user_management_service.User')
    def test_delete_user_success(self, mock_user, mock_db):
        """Test successful user deletion"""
        mock_user_obj = Mock()
        mock_user.query.get.return_value = mock_user_obj

        result = UserManagementService.delete_user(1)

        assert result is True
        mock_db.session.delete.assert_called_once_with(mock_user_obj)
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.user_management_service.User')
    def test_delete_user_not_found(self, mock_user):
        """Test deleting non-existent user"""
        mock_user.query.get.return_value = None

        result = UserManagementService.delete_user(999)

        assert result is False

    @patch('app.admin.services.user_management_service.db')
    @patch('app.admin.services.user_management_service.User')
    def test_toggle_user_status_activate(self, mock_user, mock_db):
        """Test activating user"""
        mock_user_obj = Mock()
        mock_user_obj.id = 1
        mock_user_obj.username = 'testuser'
        mock_user_obj.active = False
        mock_user.query.get.return_value = mock_user_obj

        result = UserManagementService.toggle_user_status(1)

        assert result is not None
        assert result['active'] is True
        assert result['username'] == 'testuser'
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.user_management_service.db')
    @patch('app.admin.services.user_management_service.User')
    def test_toggle_user_status_deactivate(self, mock_user, mock_db):
        """Test deactivating user"""
        mock_user_obj = Mock()
        mock_user_obj.id = 1
        mock_user_obj.username = 'testuser'
        mock_user_obj.active = True
        mock_user.query.get.return_value = mock_user_obj

        result = UserManagementService.toggle_user_status(1)

        assert result is not None
        assert result['active'] is False
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.user_management_service.User')
    def test_toggle_user_status_not_found(self, mock_user):
        """Test toggling status of non-existent user"""
        mock_user.query.get.return_value = None

        result = UserManagementService.toggle_user_status(999)

        assert result is None

    @patch('app.admin.services.user_management_service.db')
    @patch('app.admin.services.user_management_service.User')
    def test_toggle_admin_status_grant(self, mock_user, mock_db):
        """Test granting admin privileges"""
        mock_user_obj = Mock()
        mock_user_obj.id = 2
        mock_user_obj.username = 'testuser'
        mock_user_obj.is_admin = False
        mock_user.query.get.return_value = mock_user_obj

        success, message = UserManagementService.toggle_admin_status(2, 1)

        assert success is True
        assert 'granted' in message
        assert 'testuser' in message
        assert mock_user_obj.is_admin is True
        mock_db.session.commit.assert_called_once()

    @patch('app.admin.services.user_management_service.db')
    @patch('app.admin.services.user_management_service.User')
    def test_toggle_admin_status_revoke(self, mock_user, mock_db):
        """Test revoking admin privileges"""
        mock_user_obj = Mock()
        mock_user_obj.id = 2
        mock_user_obj.username = 'testuser'
        mock_user_obj.is_admin = True
        mock_user.query.get.return_value = mock_user_obj

        success, message = UserManagementService.toggle_admin_status(2, 1)

        assert success is True
        assert 'revoked' in message
        assert mock_user_obj.is_admin is False
        mock_db.session.commit.assert_called_once()

    def test_toggle_admin_status_self_modification(self):
        """Test that admin cannot modify their own status"""
        success, message = UserManagementService.toggle_admin_status(1, 1)

        assert success is False
        assert 'Cannot modify your own admin status' in message

    @patch('app.admin.services.user_management_service.User')
    def test_toggle_admin_status_user_not_found(self, mock_user):
        """Test toggling admin status for non-existent user"""
        mock_user.query.get.return_value = None

        success, message = UserManagementService.toggle_admin_status(999, 1)

        assert success is False
        assert 'User not found' in message

    @patch('app.admin.services.user_management_service.db')
    def test_get_user_activity_stats_success(self, mock_db):
        """Test successful retrieval of user activity statistics"""
        # Mock registration data
        mock_registrations = [
            (datetime(2024, 1, 1).date(), 5),
            (datetime(2024, 1, 2).date(), 3)
        ]

        # Mock login data
        mock_logins = [
            (datetime(2024, 1, 1).date(), 10),
            (datetime(2024, 1, 2).date(), 8)
        ]

        # Mock hourly activity
        mock_hourly = [
            (9, 15),
            (14, 20),
            (18, 25)
        ]

        # Configure mock to return different results for each query call
        # The method makes 3 separate query chains, so we need to mock all 3
        mock_chain_1 = Mock()
        mock_chain_1.filter.return_value.group_by.return_value.all.return_value = mock_registrations

        mock_chain_2 = Mock()
        mock_chain_2.filter.return_value.group_by.return_value.all.return_value = mock_logins

        mock_chain_3 = Mock()
        mock_chain_3.filter.return_value.group_by.return_value.all.return_value = mock_hourly

        # db.session.query is called 3 times, return different mocks each time
        mock_db.session.query.side_effect = [mock_chain_1, mock_chain_2, mock_chain_3]

        result = UserManagementService.get_user_activity_stats(days=30)

        assert 'user_registrations' in result
        assert 'user_logins' in result
        assert 'user_activity_by_hour' in result
        assert len(result['user_registrations']) == 2
        assert len(result['user_logins']) == 2
        assert len(result['user_activity_by_hour']) == 3

    @patch('app.admin.services.user_management_service.db')
    def test_get_user_activity_stats_custom_days(self, mock_db):
        """Test getting activity stats for custom number of days"""
        # Configure mock to return empty results for each query
        mock_chain_1 = Mock()
        mock_chain_1.filter.return_value.group_by.return_value.all.return_value = []

        mock_chain_2 = Mock()
        mock_chain_2.filter.return_value.group_by.return_value.all.return_value = []

        mock_chain_3 = Mock()
        mock_chain_3.filter.return_value.group_by.return_value.all.return_value = []

        mock_db.session.query.side_effect = [mock_chain_1, mock_chain_2, mock_chain_3]

        result = UserManagementService.get_user_activity_stats(days=7)

        assert result is not None
        assert isinstance(result, dict)
        assert 'user_registrations' in result
        assert 'user_logins' in result
        assert 'user_activity_by_hour' in result
        assert len(result['user_registrations']) == 0
        assert len(result['user_logins']) == 0
        assert len(result['user_activity_by_hour']) == 0


class TestUserManagementServiceIntegration:
    """Integration tests that verify the service works with real database models"""

    # These would be run with a test database
    # Example structure for future implementation:

    @pytest.mark.skip(reason="Requires database setup")
    def test_create_and_delete_user(self):
        """Integration test for user creation and deletion"""
        pass

    @pytest.mark.skip(reason="Requires database setup")
    def test_user_statistics_with_real_data(self):
        """Integration test for statistics with real user data"""
        pass

    @pytest.mark.skip(reason="Requires database setup")
    def test_module_access_toggle_persistence(self):
        """Integration test for module access toggle persistence"""
        pass
