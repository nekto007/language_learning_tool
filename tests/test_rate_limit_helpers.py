"""
Tests for rate limit helper functions
Тесты вспомогательных функций rate limiting
"""
import pytest
from unittest.mock import Mock, patch
from app.utils.rate_limit_helpers import (
    get_remote_address_key,
    get_username_key,
    get_authenticated_user_key,
    get_composite_key
)


class TestGetRemoteAddressKey:
    """Тесты получения IP адреса клиента"""

    def test_get_remote_address_from_x_forwarded_for(self, app):
        """Тест получения IP из X-Forwarded-For заголовка"""
        with app.test_request_context(headers={'X-Forwarded-For': '1.2.3.4, 5.6.7.8'}):
            result = get_remote_address_key()
            assert result == '1.2.3.4'

    def test_get_remote_address_from_x_forwarded_for_single(self, app):
        """Тест получения IP из X-Forwarded-For с одним адресом"""
        with app.test_request_context(headers={'X-Forwarded-For': '1.2.3.4'}):
            result = get_remote_address_key()
            assert result == '1.2.3.4'

    def test_get_remote_address_from_x_real_ip(self, app):
        """Тест получения IP из X-Real-IP заголовка"""
        with app.test_request_context(headers={'X-Real-IP': '9.8.7.6'}):
            result = get_remote_address_key()
            assert result == '9.8.7.6'

    def test_get_remote_address_from_remote_addr(self, app):
        """Тест получения IP из request.remote_addr"""
        with app.test_request_context(environ_base={'REMOTE_ADDR': '192.168.1.1'}):
            result = get_remote_address_key()
            assert result == '192.168.1.1'

    def test_get_remote_address_default_localhost(self, app):
        """Тест что возвращается 127.0.0.1 по умолчанию"""
        with app.test_request_context():
            result = get_remote_address_key()
            # When remote_addr is None, should return default
            assert result == '127.0.0.1'

    def test_x_forwarded_for_priority_over_x_real_ip(self, app):
        """Тест что X-Forwarded-For имеет приоритет над X-Real-IP"""
        with app.test_request_context(headers={
            'X-Forwarded-For': '1.2.3.4',
            'X-Real-IP': '5.6.7.8'
        }):
            result = get_remote_address_key()
            assert result == '1.2.3.4'


class TestGetUsernameKey:
    """Тесты получения ключа по username"""

    def test_get_username_from_json(self, app):
        """Тест получения username из JSON данных"""
        with app.test_request_context(
            json={'username': 'testuser'},
            content_type='application/json'
        ):
            result = get_username_key()
            assert result == 'username:testuser'

    def test_get_username_from_form(self, app):
        """Тест получения username из form data"""
        with app.test_request_context(
            data={'username': 'formuser'},
            method='POST'
        ):
            result = get_username_key()
            assert result == 'username:formuser'

    def test_get_username_from_form_username_or_email(self, app):
        """Тест получения username из username_or_email поля"""
        with app.test_request_context(
            data={'username_or_email': 'emailuser'},
            method='POST'
        ):
            result = get_username_key()
            assert result == 'username:emailuser'

    def test_get_username_from_authenticated_user(self, app, test_user):
        """Тест получения username от аутентифицированного пользователя"""
        with app.test_request_context():
            from flask_login import login_user
            login_user(test_user)

            result = get_username_key()
            assert result == f'username:{test_user.username}'

    def test_get_username_fallback_to_ip(self, app):
        """Тест fallback на IP когда username не найден"""
        with app.test_request_context(environ_base={'REMOTE_ADDR': '1.2.3.4'}):
            result = get_username_key()
            assert result == 'ip:1.2.3.4'

    def test_get_username_invalid_json(self, app):
        """Тест обработки невалидного JSON"""
        with app.test_request_context(
            data='invalid json',
            content_type='application/json',
            method='POST',
            environ_base={'REMOTE_ADDR': '1.2.3.4'}
        ):
            result = get_username_key()
            # Should fallback to IP
            assert result.startswith('ip:')


class TestGetAuthenticatedUserKey:
    """Тесты получения ключа для аутентифицированного пользователя"""

    def test_get_key_for_authenticated_user(self, app, test_user):
        """Тест получения ключа для аутентифицированного пользователя"""
        with app.test_request_context():
            from flask_login import login_user
            login_user(test_user)

            result = get_authenticated_user_key()
            assert result == f'user:{test_user.id}'

    def test_get_key_for_unauthenticated_user(self, app):
        """Тест fallback на IP для неаутентифицированного пользователя"""
        with app.test_request_context(environ_base={'REMOTE_ADDR': '5.6.7.8'}):
            result = get_authenticated_user_key()
            assert result == 'ip:5.6.7.8'

    def test_get_key_respects_proxy_headers(self, app):
        """Тест что учитываются прокси заголовки при fallback на IP"""
        with app.test_request_context(headers={'X-Forwarded-For': '10.0.0.1'}):
            result = get_authenticated_user_key()
            assert result == 'ip:10.0.0.1'


class TestGetCompositeKey:
    """Тесты получения комбинированного ключа"""

    def test_composite_key_with_username_json(self, app):
        """Тест комбинированного ключа с username из JSON"""
        with app.test_request_context(
            json={'username': 'testuser'},
            content_type='application/json',
            environ_base={'REMOTE_ADDR': '1.2.3.4'}
        ):
            result = get_composite_key()
            assert result == '1.2.3.4:username:testuser'

    def test_composite_key_with_username_form(self, app):
        """Тест комбинированного ключа с username из form"""
        with app.test_request_context(
            data={'username': 'formuser'},
            method='POST',
            headers={'X-Forwarded-For': '5.6.7.8'}
        ):
            result = get_composite_key()
            assert result == '5.6.7.8:username:formuser'

    def test_composite_key_with_authenticated_user(self, app, test_user):
        """Тест комбинированного ключа с аутентифицированным пользователем"""
        with app.test_request_context(environ_base={'REMOTE_ADDR': '9.8.7.6'}):
            from flask_login import login_user
            login_user(test_user)

            result = get_composite_key()
            assert result == f'9.8.7.6:username:{test_user.username}'

    def test_composite_key_without_username(self, app):
        """Тест комбинированного ключа без username (только IP)"""
        with app.test_request_context(environ_base={'REMOTE_ADDR': '3.4.5.6'}):
            result = get_composite_key()
            assert result == '3.4.5.6'

    def test_composite_key_with_proxy_headers(self, app):
        """Тест что комбинированный ключ учитывает прокси заголовки"""
        with app.test_request_context(
            headers={'X-Real-IP': '11.22.33.44'},
            json={'username': 'proxyuser'},
            content_type='application/json'
        ):
            result = get_composite_key()
            assert result == '11.22.33.44:username:proxyuser'


class TestIntegration:
    """Интеграционные тесты"""

    def test_all_functions_work_together(self, app, test_user):
        """Тест что все функции работают согласованно"""
        with app.test_request_context(
            json={'username': 'testuser'},
            content_type='application/json',
            headers={'X-Forwarded-For': '1.1.1.1, 2.2.2.2'},
            method='POST'
        ):
            from flask_login import login_user
            login_user(test_user)

            # Все функции должны возвращать корректные результаты
            ip_key = get_remote_address_key()
            username_key = get_username_key()
            user_key = get_authenticated_user_key()
            composite_key = get_composite_key()

            assert ip_key == '1.1.1.1'
            assert username_key == 'username:testuser'
            assert user_key == f'user:{test_user.id}'
            assert composite_key == '1.1.1.1:username:testuser'
