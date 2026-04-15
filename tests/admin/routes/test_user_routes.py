"""Route tests for admin user management pages."""

from unittest.mock import patch


class TestToggleMissionPlanRoute:
    """Tests for mission plan admin toggle route."""

    @patch('app.admin.routes.user_routes.UserManagementService.toggle_mission_plan')
    def test_toggle_mission_plan_success(self, mock_toggle, admin_client, mock_admin_user):
        """Successful toggle redirects back to users list."""
        mock_toggle.return_value = {
            'user_id': 42,
            'username': 'learner',
            'use_mission_plan': True,
        }

        response = admin_client.post(
            '/admin/users/42/toggle_mission_plan',
            data={'next': '/admin/users'},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.location.endswith('/admin/users')
        mock_toggle.assert_called_once_with(42)

    @patch('app.admin.routes.user_routes.UserManagementService.toggle_mission_plan')
    def test_toggle_mission_plan_not_found(self, mock_toggle, admin_client, mock_admin_user):
        """Missing user still redirects with error flash."""
        mock_toggle.return_value = None

        response = admin_client.post(
            '/admin/users/999/toggle_mission_plan',
            data={'next': '/admin/users'},
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.location.endswith('/admin/users')
        mock_toggle.assert_called_once_with(999)

    def test_toggle_mission_plan_requires_admin(self, client):
        """Toggle route requires admin authentication."""
        response = client.post('/admin/users/42/toggle_mission_plan', follow_redirects=False)
        assert response.status_code == 302
