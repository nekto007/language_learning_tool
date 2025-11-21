"""
Tests for Utils Decorators (app/utils/decorators.py)

Tests admin_required decorator:
- Allows admin users
- Blocks non-admin users
- Blocks unauthenticated users
- Shows flash message and redirects

Coverage target: 100% for app/utils/decorators.py
"""
import pytest
from unittest.mock import Mock, patch


class TestAdminRequired:
    """Test admin_required decorator"""

    def test_allows_admin_user(self, app):
        """Test allows authenticated admin user"""
        from app.utils.decorators import admin_required

        @admin_required
        def test_view():
            return 'Success'

        with app.test_request_context():
            with patch('app.utils.decorators.current_user') as mock_user:
                mock_user.is_authenticated = True
                mock_user.is_admin = True

                result = test_view()

        assert result == 'Success'

    def test_blocks_non_admin_user(self, app):
        """Test blocks authenticated non-admin user"""
        from app.utils.decorators import admin_required
        from flask import url_for

        @admin_required
        def test_view():
            return 'Success'

        with app.test_request_context():
            with patch('app.utils.decorators.current_user') as mock_user:
                mock_user.is_authenticated = True
                mock_user.is_admin = False

                with patch('app.utils.decorators.flash') as mock_flash:
                    with patch('app.utils.decorators.redirect') as mock_redirect:
                        with patch('app.utils.decorators.url_for', return_value='/dashboard'):
                            result = test_view()

                mock_flash.assert_called_once_with(
                    'You need administrator privileges to access this page.',
                    'danger'
                )
                mock_redirect.assert_called_once()

    def test_blocks_unauthenticated_user(self, app):
        """Test blocks unauthenticated user"""
        from app.utils.decorators import admin_required

        @admin_required
        def test_view():
            return 'Success'

        with app.test_request_context():
            with patch('app.utils.decorators.current_user') as mock_user:
                mock_user.is_authenticated = False

                with patch('app.utils.decorators.flash') as mock_flash:
                    with patch('app.utils.decorators.redirect'):
                        with patch('app.utils.decorators.url_for', return_value='/dashboard'):
                            test_view()

                mock_flash.assert_called_once_with(
                    'You need administrator privileges to access this page.',
                    'danger'
                )

    def test_redirects_to_dashboard(self, app):
        """Test redirects to words.dashboard"""
        from app.utils.decorators import admin_required

        @admin_required
        def test_view():
            return 'Success'

        with app.test_request_context():
            with patch('app.utils.decorators.current_user') as mock_user:
                mock_user.is_authenticated = False

                with patch('app.utils.decorators.flash'):
                    with patch('app.utils.decorators.redirect') as mock_redirect:
                        with patch('app.utils.decorators.url_for', return_value='/dashboard') as mock_url_for:
                            test_view()

                mock_url_for.assert_called_once_with('words.dashboard')
                mock_redirect.assert_called_once_with('/dashboard')

    def test_preserves_function_name(self):
        """Test decorator preserves function name and metadata"""
        from app.utils.decorators import admin_required

        @admin_required
        def my_view_function():
            """My docstring"""
            return 'Success'

        assert my_view_function.__name__ == 'my_view_function'
        assert my_view_function.__doc__ == 'My docstring'
