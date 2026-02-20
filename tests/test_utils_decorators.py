"""
Tests for admin_required decorator (app/admin/utils/decorators.py)

Tests:
- Allows admin users
- Blocks non-admin users
- Blocks unauthenticated users
- Shows flash message and redirects to auth.login
- Preserves function metadata

Coverage target: 100% for admin_required in app/admin/utils/decorators.py
"""
import pytest
from unittest.mock import patch


class TestAdminRequired:
    """Test admin_required decorator"""

    def test_allows_admin_user(self, app):
        """Test allows authenticated admin user"""
        with patch('app.admin.utils.decorators.login_required', lambda f: f):
            from app.admin.utils.decorators import admin_required

            @admin_required
            def test_view():
                return 'Success'

            with app.test_request_context():
                with patch('app.admin.utils.decorators.current_user') as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.is_admin = True
                    result = test_view()

        assert result == 'Success'

    def test_blocks_non_admin_user(self, app):
        """Test blocks authenticated non-admin user"""
        with patch('app.admin.utils.decorators.login_required', lambda f: f):
            from app.admin.utils.decorators import admin_required

            @admin_required
            def test_view():
                return 'Success'

            with app.test_request_context():
                with patch('app.admin.utils.decorators.current_user') as mock_user:
                    mock_user.is_authenticated = True
                    mock_user.is_admin = False

                    with patch('app.admin.utils.decorators.flash') as mock_flash:
                        with patch('app.admin.utils.decorators.redirect') as mock_redirect:
                            with patch('app.admin.utils.decorators.url_for', return_value='/login'):
                                test_view()

                    mock_flash.assert_called_once_with(
                        'У вас нет прав для доступа к этой странице.',
                        'danger'
                    )
                    mock_redirect.assert_called_once()

    def test_blocks_unauthenticated_user(self, app):
        """Test blocks unauthenticated user"""
        with patch('app.admin.utils.decorators.login_required', lambda f: f):
            from app.admin.utils.decorators import admin_required

            @admin_required
            def test_view():
                return 'Success'

            with app.test_request_context():
                with patch('app.admin.utils.decorators.current_user') as mock_user:
                    mock_user.is_authenticated = False

                    with patch('app.admin.utils.decorators.flash') as mock_flash:
                        with patch('app.admin.utils.decorators.redirect'):
                            with patch('app.admin.utils.decorators.url_for', return_value='/login'):
                                test_view()

                    mock_flash.assert_called_once_with(
                        'У вас нет прав для доступа к этой странице.',
                        'danger'
                    )

    def test_redirects_to_login(self, app):
        """Test redirects to auth.login"""
        with patch('app.admin.utils.decorators.login_required', lambda f: f):
            from app.admin.utils.decorators import admin_required

            @admin_required
            def test_view():
                return 'Success'

            with app.test_request_context():
                with patch('app.admin.utils.decorators.current_user') as mock_user:
                    mock_user.is_authenticated = False

                    with patch('app.admin.utils.decorators.flash'):
                        with patch('app.admin.utils.decorators.redirect') as mock_redirect:
                            with patch('app.admin.utils.decorators.url_for', return_value='/login') as mock_url_for:
                                test_view()

                    mock_url_for.assert_called_once_with('auth.login')
                    mock_redirect.assert_called_once_with('/login')

    def test_preserves_function_name(self):
        """Test decorator preserves function name and metadata"""
        from app.admin.utils.decorators import admin_required

        @admin_required
        def my_view_function():
            """My docstring"""
            return 'Success'

        assert my_view_function.__name__ == 'my_view_function'
        assert my_view_function.__doc__ == 'My docstring'
