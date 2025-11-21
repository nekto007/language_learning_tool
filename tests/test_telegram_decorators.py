"""
Tests for Telegram Decorators (app/telegram/decorators.py)

Tests telegram authentication decorators:
- telegram_auth_required - main auth decorator
- telegram_read_required - convenience decorator for read scope
- telegram_write_required - convenience decorator for write scope
- telegram_admin_required - convenience decorator for admin scope

Coverage target: 100% for app/telegram/decorators.py
"""
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, timezone


class TestTelegramAuthRequired:
    """Test telegram_auth_required decorator"""

    def test_returns_401_when_token_missing(self, app):
        """Test returns 401 when X-Telegram-Token header is missing"""
        from app.telegram.decorators import telegram_auth_required

        @telegram_auth_required('read')
        def test_route(token, user):
            return {'success': True}

        with app.test_request_context(headers={}):
            response, status_code = test_route()

            assert status_code == 401
            assert response.json['success'] is False
            assert 'Missing authentication token' in response.json['error']

    def test_returns_401_when_token_invalid(self, app):
        """Test returns 401 when token is invalid"""
        from app.telegram.decorators import telegram_auth_required

        @telegram_auth_required('read')
        def test_route(token, user):
            return {'success': True}

        with app.test_request_context(headers={'X-Telegram-Token': 'invalid'}):
            with patch('app.telegram.decorators.TelegramToken.get_valid_token', return_value=None):
                response, status_code = test_route()

                assert status_code == 401
                assert response.json['success'] is False
                assert 'Invalid or expired' in response.json['error']

    def test_returns_403_when_insufficient_scope(self, app):
        """Test returns 403 when token lacks required scope"""
        from app.telegram.decorators import telegram_auth_required

        @telegram_auth_required('write')
        def test_route(token, user):
            return {'success': True}

        # Mock token with read scope only
        mock_token = Mock()
        mock_token.has_scope.return_value = False
        mock_token.user = Mock()

        with app.test_request_context(headers={'X-Telegram-Token': 'valid_token'}):
            with patch('app.telegram.decorators.TelegramToken.get_valid_token', return_value=mock_token):
                response, status_code = test_route()

                assert status_code == 403
                assert response.json['success'] is False
                assert 'Insufficient permissions' in response.json['error']
                assert 'write' in response.json['error']

    def test_allows_access_with_valid_token_and_scope(self, app):
        """Test allows access when token is valid and has required scope"""
        from app.telegram.decorators import telegram_auth_required

        @telegram_auth_required('read')
        def test_route(token, user):
            return {'success': True, 'user_id': user.id}

        # Mock valid token with correct scope
        mock_token = Mock()
        mock_token.has_scope.return_value = True
        mock_user = Mock()
        mock_user.id = 123
        mock_token.user = mock_user

        with app.test_request_context(headers={'X-Telegram-Token': 'valid_token'}):
            with patch('app.telegram.decorators.TelegramToken.get_valid_token', return_value=mock_token):
                result = test_route()

                assert result['success'] is True
                assert result['user_id'] == 123
                # Verify scope was checked
                mock_token.has_scope.assert_called_once_with('read')

    def test_passes_token_and_user_to_route(self, app):
        """Test passes token and user objects to decorated function"""
        from app.telegram.decorators import telegram_auth_required

        @telegram_auth_required('read')
        def test_route(token, user):
            return {
                'token_value': token.token,
                'user_name': user.username
            }

        # Mock valid token
        mock_token = Mock()
        mock_token.has_scope.return_value = True
        mock_token.token = 'test_token_123'
        mock_user = Mock()
        mock_user.username = 'test_user'
        mock_token.user = mock_user

        with app.test_request_context(headers={'X-Telegram-Token': 'valid_token'}):
            with patch('app.telegram.decorators.TelegramToken.get_valid_token', return_value=mock_token):
                result = test_route()

                assert result['token_value'] == 'test_token_123'
                assert result['user_name'] == 'test_user'


class TestConvenienceDecorators:
    """Test convenience decorators"""

    def test_telegram_read_required_decorator(self, app):
        """Test telegram_read_required convenience decorator"""
        from app.telegram.decorators import telegram_read_required

        @telegram_read_required
        def test_route(token, user):
            return {'success': True}

        # Mock valid token with read scope
        mock_token = Mock()
        mock_token.has_scope.return_value = True
        mock_token.user = Mock()

        with app.test_request_context(headers={'X-Telegram-Token': 'valid'}):
            with patch('app.telegram.decorators.TelegramToken.get_valid_token', return_value=mock_token):
                result = test_route()

                assert result['success'] is True
                # Verify 'read' scope was checked
                mock_token.has_scope.assert_called_with('read')

    def test_telegram_write_required_decorator(self, app):
        """Test telegram_write_required convenience decorator"""
        from app.telegram.decorators import telegram_write_required

        @telegram_write_required
        def test_route(token, user):
            return {'success': True}

        # Mock valid token with write scope
        mock_token = Mock()
        mock_token.has_scope.return_value = True
        mock_token.user = Mock()

        with app.test_request_context(headers={'X-Telegram-Token': 'valid'}):
            with patch('app.telegram.decorators.TelegramToken.get_valid_token', return_value=mock_token):
                result = test_route()

                assert result['success'] is True
                # Verify 'write' scope was checked
                mock_token.has_scope.assert_called_with('write')

    def test_telegram_admin_required_decorator(self, app):
        """Test telegram_admin_required convenience decorator"""
        from app.telegram.decorators import telegram_admin_required

        @telegram_admin_required
        def test_route(token, user):
            return {'success': True}

        # Mock valid token with admin scope
        mock_token = Mock()
        mock_token.has_scope.return_value = True
        mock_token.user = Mock()

        with app.test_request_context(headers={'X-Telegram-Token': 'valid'}):
            with patch('app.telegram.decorators.TelegramToken.get_valid_token', return_value=mock_token):
                result = test_route()

                assert result['success'] is True
                # Verify 'admin' scope was checked
                mock_token.has_scope.assert_called_with('admin')

    def test_read_decorator_rejects_insufficient_scope(self, app):
        """Test read decorator rejects when scope insufficient"""
        from app.telegram.decorators import telegram_read_required

        @telegram_read_required
        def test_route(token, user):
            return {'success': True}

        # Mock token without read scope
        mock_token = Mock()
        mock_token.has_scope.return_value = False
        mock_token.user = Mock()

        with app.test_request_context(headers={'X-Telegram-Token': 'valid'}):
            with patch('app.telegram.decorators.TelegramToken.get_valid_token', return_value=mock_token):
                response, status_code = test_route()

                assert status_code == 403
                assert 'read' in response.json['error']


class TestDecoratorFunctionalityPreservation:
    """Test decorator preserves function metadata"""

    def test_preserves_function_name(self):
        """Test decorator preserves original function name"""
        from app.telegram.decorators import telegram_auth_required

        @telegram_auth_required('read')
        def my_function(token, user):
            """My docstring"""
            pass

        assert my_function.__name__ == 'my_function'

    def test_preserves_function_docstring(self):
        """Test decorator preserves original function docstring"""
        from app.telegram.decorators import telegram_auth_required

        @telegram_auth_required('read')
        def my_function(token, user):
            """My docstring"""
            pass

        assert my_function.__doc__ == 'My docstring'

    def test_read_decorator_preserves_metadata(self):
        """Test convenience decorator preserves metadata"""
        from app.telegram.decorators import telegram_read_required

        @telegram_read_required
        def my_read_function(token, user):
            """Read function"""
            return True

        assert my_read_function.__name__ == 'my_read_function'
        assert 'Read function' in my_read_function.__doc__
