"""
Shared fixtures for admin route tests
"""
import pytest
from unittest.mock import patch


@pytest.fixture
def mock_admin_user(admin_user):
    """Mock current_user to be an authenticated admin for route testing"""
    with patch('app.admin.utils.decorators.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.id = admin_user.id
        mock_user.username = admin_user.username
        yield mock_user