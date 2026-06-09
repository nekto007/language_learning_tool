"""Tests for the /admin/stats route (user_routes.stats + CSV export).

Verifies the page renders with real-data context (no more mock placeholders),
the period selector maps to the right window, and CSV export works.
"""
from unittest.mock import patch

import pytest

_ACTIVITY = {
    'user_registrations': [{'date': '2026-06-01', 'count': 5}],
    'user_logins': [{'date': '2026-06-01', 'count': 3}],
    'user_activity_by_hour': [{'hour': 14, 'count': 7}],
}
_CONTENT = {
    'completion_by_level': [{'level': 'A1', 'rate': 85}, {'level': 'A2', 'rate': 60}],
    'content_distribution': [{'type': 'card', 'count': 172}, {'type': 'quiz', 'count': 86}],
    'top_users': [{'username': 'alice', 'completed': 12, 'words': 340}],
    'popular_content': [{'title': 'Verb TO BE', 'type': 'grammar', 'completions': 50}],
}


class TestAdminStatsRoute:
    @patch('app.admin.routes.user_routes.UserManagementService.get_platform_content_stats', return_value=_CONTENT)
    @patch('app.admin.routes.user_routes.UserManagementService.get_user_activity_stats', return_value=_ACTIVITY)
    @pytest.mark.smoke
    def test_stats_page_renders_real_data(self, m_act, m_cont, admin_client, mock_admin_user):
        resp = admin_client.get('/admin/stats')
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # real data surfaced (not the old hardcoded john_doe / Базовые приветствия)
        assert 'alice' in body
        assert 'Verb TO BE' in body
        assert 'john_doe' not in body

    @patch('app.admin.routes.user_routes.UserManagementService.get_platform_content_stats', return_value=_CONTENT)
    @patch('app.admin.routes.user_routes.UserManagementService.get_user_activity_stats', return_value=_ACTIVITY)
    def test_period_week_maps_to_7_days(self, m_act, m_cont, admin_client, mock_admin_user):
        resp = admin_client.get('/admin/stats?period=week')
        assert resp.status_code == 200
        m_act.assert_called_once_with(days=7)
        m_cont.assert_called_once_with(days=7)

    @patch('app.admin.routes.user_routes.UserManagementService.get_platform_content_stats', return_value=_CONTENT)
    def test_csv_export(self, m_cont, admin_client, mock_admin_user):
        resp = admin_client.get('/admin/stats?export=csv')
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type
        body = resp.get_data(as_text=True)
        assert 'alice' in body and 'Verb TO BE' in body

    def test_requires_admin(self, client):
        resp = client.get('/admin/stats')
        assert resp.status_code == 302
