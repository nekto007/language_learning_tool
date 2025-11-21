"""Tests for modules routes"""
import pytest
import uuid
from unittest.mock import patch


@pytest.fixture
def test_modules(db_session):
    """Create test modules"""
    from app.modules.models import SystemModule

    unique_id = uuid.uuid4().hex[:8]
    modules = []
    for i in range(3):
        module = SystemModule(
            code=f'test_module_{unique_id}_{i}',
            name=f'Test Module {i}',
            description=f'Description for module {i}',
            is_active=True,
            order=i
        )
        db_session.add(module)
        modules.append(module)

    db_session.commit()
    return modules


@pytest.fixture
def user_modules(db_session, test_user, test_modules):
    """Create user module associations"""
    from app.modules.models import UserModule

    user_modules = []
    # Enable only the first two modules
    for i, module in enumerate(test_modules[:2]):
        user_module = UserModule(
            user_id=test_user.id,
            module_id=module.id,
            is_enabled=True
        )
        db_session.add(user_module)
        user_modules.append(user_module)

    db_session.commit()
    return user_modules


class TestGetUserModules:
    """Test /api/modules/user endpoint"""

    def test_get_user_modules_success(self, authenticated_client, test_modules, user_modules):
        """Test getting user modules successfully"""
        response = authenticated_client.get(
            '/api/modules/user'
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'modules' in data
        # Should return only enabled modules (2)
        assert len(data['modules']) == 2

    def test_get_user_modules_unauthenticated(self, client):
        """Test getting user modules without authentication"""
        response = client.get('/api/modules/user')

        assert response.status_code == 401

    def test_get_user_modules_empty(self, authenticated_client):
        """Test getting user modules when user has no modules"""
        response = authenticated_client.get(
            '/api/modules/user',
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['modules'] == []


class TestGetAllModules:
    """Test /api/modules/all endpoint"""

    def test_get_all_modules_success(self, authenticated_client, test_modules):
        """Test getting all active modules"""
        response = authenticated_client.get(
            '/api/modules/all',
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'modules' in data
        assert len(data['modules']) == 3

    def test_get_all_modules_unauthenticated(self, client):
        """Test getting all modules without authentication"""
        response = client.get('/api/modules/all')

        assert response.status_code == 401

    def test_get_all_modules_returns_module_data(self, authenticated_client, test_modules):
        """Test that returned modules contain expected data"""
        response = authenticated_client.get(
            '/api/modules/all',
        )

        assert response.status_code == 200
        data = response.get_json()
        modules = data['modules']

        for module in modules:
            assert 'code' in module
            assert 'name' in module
            assert 'description' in module
            assert 'level' in module


class TestGetEnabledModuleCodes:
    """Test /api/modules/enabled-codes endpoint"""

    def test_get_enabled_codes_success(self, authenticated_client, test_modules, user_modules):
        """Test getting enabled module codes"""
        response = authenticated_client.get(
            '/api/modules/enabled-codes',
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'codes' in data
        # Should return 2 enabled module codes
        assert len(data['codes']) == 2
        assert 'test_module_0' in data['codes']
        assert 'test_module_1' in data['codes']

    def test_get_enabled_codes_unauthenticated(self, client):
        """Test getting enabled codes without authentication"""
        response = client.get('/api/modules/enabled-codes')

        assert response.status_code == 401

    def test_get_enabled_codes_empty(self, authenticated_client):
        """Test getting enabled codes when user has no enabled modules"""
        response = authenticated_client.get(
            '/api/modules/enabled-codes',
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['codes'] == []


class TestModuleSettings:
    """Test /settings endpoint"""

    def test_settings_page_renders(self, authenticated_client, test_modules):
        """Test that settings page renders successfully"""
        response = authenticated_client.get(
            '/modules/settings',
        )

        assert response.status_code == 200
        assert b'modules/settings.html' in response.data or len(response.data) > 0

    def test_settings_page_unauthenticated(self, client):
        """Test settings page without authentication"""
        response = client.get('/modules/settings')

        assert response.status_code == 302  # Redirect to login

    def test_settings_page_with_user_modules(self, authenticated_client, test_modules, user_modules):
        """Test settings page displays user modules correctly"""
        response = authenticated_client.get(
            '/modules/settings',
        )

        assert response.status_code == 200


class TestToggleModule:
    """Test /api/modules/<int:module_id>/toggle endpoint"""

    def test_toggle_module_enable(self, authenticated_client, test_modules):
        """Test enabling a module"""
        module_id = test_modules[0].id

        response = authenticated_client.post(
            f'/api/modules/{module_id}/toggle',
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'enabled' in data

    def test_toggle_module_disable(self, authenticated_client, test_modules, user_modules):
        """Test disabling an enabled module"""
        # Get the first enabled module
        module_id = test_modules[0].id

        response = authenticated_client.post(
            f'/api/modules/{module_id}/toggle',
        )

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_toggle_module_unauthenticated(self, client, test_modules):
        """Test toggling module without authentication"""
        module_id = test_modules[0].id

        response = client.post(f'/api/modules/{module_id}/toggle')

        assert response.status_code == 401

    def test_toggle_nonexistent_module(self, authenticated_client):
        """Test toggling a non-existent module"""
        response = authenticated_client.post(
            '/api/modules/99999/toggle',
        )

        assert response.status_code == 500
        data = response.get_json()
        assert data['success'] is False
        assert 'error' in data

    @patch('app.modules.service.ModuleService.toggle_module_for_user')
    def test_toggle_module_service_error(self, mock_toggle, authenticated_client, test_modules):
        """Test handling service errors"""
        mock_toggle.side_effect = Exception('Service error')
        module_id = test_modules[0].id

        response = authenticated_client.post(
            f'/api/modules/{module_id}/toggle',
        )

        assert response.status_code == 500
        data = response.get_json()
        assert data['success'] is False
        assert 'Service error' in data['error']