"""
Tests for modules decorators
Тесты декораторов модулей
"""
import pytest
from unittest.mock import patch, MagicMock
from app.modules.decorators import module_required, admin_or_module_owner


class TestModuleRequired:
    """Тесты декоратора module_required"""

    def test_module_required_preserves_function_name(self):
        """Тест что декоратор сохраняет имя функции"""
        @module_required('curriculum')
        def my_view_function():
            return 'Success'

        assert my_view_function.__name__ == 'my_view_function'

    def test_module_required_is_callable(self):
        """Тест что декоратор возвращает вызываемую функцию"""
        @module_required('curriculum')
        def my_view():
            return 'Success'

        assert callable(my_view)

    @patch('app.modules.decorators.current_user')
    @patch('app.modules.decorators.ModuleService.is_module_enabled_for_user')
    def test_module_required_checks_authentication(self, mock_service, mock_user):
        """Тест проверки аутентификации"""
        mock_user.is_authenticated = False

        @module_required('curriculum')
        def view():
            return 'Success'

        with pytest.raises(Exception):
            # Should try to redirect when not authenticated
            view()

    @patch('app.modules.decorators.current_user')
    @patch('app.modules.decorators.ModuleService.is_module_enabled_for_user')
    def test_module_required_calls_service(self, mock_service, mock_user):
        """Тест что вызывается сервис проверки модуля"""
        mock_user.is_authenticated = True
        mock_user.id = 1
        mock_service.return_value = True

        @module_required('curriculum')
        def view():
            return 'Success'

        try:
            view()
        except:
            pass

        # Service should be called with user_id and module_code
        mock_service.assert_called_with(1, 'curriculum')


class TestAdminOrModuleOwner:
    """Тесты декоратора admin_or_module_owner"""

    def test_admin_or_module_owner_preserves_function_name(self):
        """Тест что декоратор сохраняет имя функции"""
        @admin_or_module_owner('curriculum')
        def my_admin_view():
            return 'Success'

        assert my_admin_view.__name__ == 'my_admin_view'

    def test_admin_or_module_owner_is_callable(self):
        """Тест что декоратор возвращает вызываемую функцию"""
        @admin_or_module_owner()
        def my_view():
            return 'Success'

        assert callable(my_view)

    @patch('app.modules.decorators.current_user')
    def test_admin_or_module_owner_checks_authentication(self, mock_user):
        """Тест проверки аутентификации"""
        mock_user.is_authenticated = False

        @admin_or_module_owner('curriculum')
        def view():
            return 'Success'

        with pytest.raises(Exception):
            view()

    @patch('app.modules.decorators.current_user')
    def test_admin_or_module_owner_admin_access(self, mock_user):
        """Тест что админ получает доступ"""
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        @admin_or_module_owner('curriculum')
        def view():
            return 'Success'

        result = view()
        assert result == 'Success'

    @patch('app.modules.decorators.current_user')
    @patch('app.modules.decorators.ModuleService.is_module_enabled_for_user')
    def test_admin_or_module_owner_non_admin_calls_service(self, mock_service, mock_user):
        """Тест что не-админ вызывает проверку модуля"""
        mock_user.is_authenticated = True
        mock_user.is_admin = False
        mock_user.id = 1
        mock_service.return_value = True

        @admin_or_module_owner('curriculum')
        def view():
            return 'Success'

        try:
            view()
        except:
            pass

        mock_service.assert_called_with(1, 'curriculum')

    @patch('app.modules.decorators.current_user')
    def test_admin_or_module_owner_without_module_code(self, mock_user):
        """Тест декоратора без кода модуля"""
        mock_user.is_authenticated = True
        mock_user.is_admin = False

        @admin_or_module_owner()
        def view():
            return 'Success'

        result = view()
        assert result == 'Success'

    @patch('app.modules.decorators.current_user')
    @patch('app.modules.decorators.ModuleService.is_module_enabled_for_user')
    def test_admin_or_module_owner_admin_bypasses_service(self, mock_service, mock_user):
        """Тест что админ не вызывает сервис"""
        mock_user.is_authenticated = True
        mock_user.is_admin = True

        @admin_or_module_owner('curriculum')
        def view():
            return 'Success'

        result = view()

        # Service should NOT be called for admin
        assert not mock_service.called
        assert result == 'Success'
