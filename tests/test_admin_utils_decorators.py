"""
Tests for Admin Utils Decorators (app/admin/utils/decorators.py)

Tests admin decorators:
- handle_admin_errors - error handling decorator
- cache_result - caching decorator (partial coverage)

Note: admin_required requires Flask-Login session which is complex to test,
so it's tested in integration tests instead.

Coverage target: 70%+ for app/admin/utils/decorators.py
"""
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestHandleAdminErrors:
    """Test handle_admin_errors decorator"""

    def test_returns_function_result_on_success(self, app):
        """Test returns function result when no error"""
        from app.admin.utils.decorators import handle_admin_errors

        @handle_admin_errors(return_json=True)
        def successful_func():
            return {'success': True, 'data': 'value'}

        with app.test_request_context():
            result = successful_func()

        assert result == {'success': True, 'data': 'value'}

    def test_returns_json_error_on_exception(self, app):
        """Test returns JSON error when exception raised"""
        from app.admin.utils.decorators import handle_admin_errors

        @handle_admin_errors(return_json=True)
        def failing_func():
            raise ValueError("Test error")

        with app.test_request_context():
            response, status_code = failing_func()
            result = response.get_json() if hasattr(response, 'get_json') else response

        assert result['success'] is False
        assert result['error'] == 'Внутренняя ошибка сервера'
        assert result['operation'] == 'failing_func'
        assert status_code == 500

    def test_rolls_back_database_on_error(self, app, db_session):
        """Test rolls back database session on error"""
        from app.admin.utils.decorators import handle_admin_errors

        @handle_admin_errors(return_json=True)
        def failing_func():
            raise Exception("Database error")

        with app.test_request_context():
            with patch('app.admin.utils.decorators.db.session.rollback') as mock_rollback:
                result, status_code = failing_func()

            mock_rollback.assert_called_once()

    def test_logs_error_with_traceback(self, app):
        """Test logs error with full traceback"""
        from app.admin.utils.decorators import handle_admin_errors

        @handle_admin_errors(return_json=True)
        def failing_func():
            raise RuntimeError("Test error")

        with app.test_request_context():
            with patch('app.admin.utils.decorators.logger') as mock_logger:
                result, status_code = failing_func()

            mock_logger.error.assert_called_once()
            call_args = mock_logger.error.call_args
            assert 'Test error' in str(call_args)
            assert call_args[1]['exc_info'] is True

    def test_handles_rollback_failure(self, app):
        """Test handles rollback failure gracefully"""
        from app.admin.utils.decorators import handle_admin_errors

        @handle_admin_errors(return_json=True)
        def failing_func():
            raise Exception("Test error")

        with app.test_request_context():
            with patch('app.admin.utils.decorators.db.session.rollback', side_effect=Exception("Rollback failed")):
                # Should not raise exception, should handle gracefully
                response, status_code = failing_func()
                result = response.get_json() if hasattr(response, 'get_json') else response

            assert result['success'] is False
            assert status_code == 500

    def test_returns_redirect_when_return_json_false(self, app):
        """Test returns redirect with flash when return_json=False"""
        from app.admin.utils.decorators import handle_admin_errors

        @handle_admin_errors(return_json=False)
        def failing_func():
            raise ValueError("Test error")

        with app.test_request_context():
            with patch('app.admin.utils.decorators.flash') as mock_flash:
                with patch('app.admin.utils.decorators.redirect') as mock_redirect:
                    with patch('app.admin.utils.decorators.url_for', return_value='/admin/dashboard'):
                        result = failing_func()

            mock_flash.assert_called_once_with(
                'Произошла внутренняя ошибка. Попробуйте позже.', 'danger'
            )
            mock_redirect.assert_called_once()

    def test_preserves_function_metadata(self):
        """Test decorator preserves function metadata"""
        from app.admin.utils.decorators import handle_admin_errors

        @handle_admin_errors()
        def my_func():
            """My function docstring"""
            pass

        assert my_func.__name__ == 'my_func'
        assert my_func.__doc__ == 'My function docstring'


class TestCacheResult:
    """Test cache_result decorator"""

    def test_preserves_function_metadata(self):
        """Test decorator preserves function metadata"""
        from app.admin.utils.decorators import cache_result

        @cache_result(key='test', timeout=300)
        def my_cached_func():
            """My cached function"""
            return 42

        assert my_cached_func.__name__ == 'my_cached_func'
        assert my_cached_func.__doc__ == 'My cached function'
