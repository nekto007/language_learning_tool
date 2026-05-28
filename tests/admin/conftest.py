"""
Shared fixtures for tests/admin/ (all admin tests, including non-route tests).
"""
import pytest
from unittest.mock import patch


@pytest.fixture
def mock_admin_user(admin_user):
    """Patch current_user in the admin decorators module so admin_required passes."""
    with patch('app.admin.utils.decorators.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.id = admin_user.id
        mock_user.username = admin_user.username
        yield mock_user
