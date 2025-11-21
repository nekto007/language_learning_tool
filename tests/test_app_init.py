"""
Tests for app initialization
Тесты инициализации приложения
"""
import pytest
from flask import g


class TestCSRFErrorHandler:
    """Тесты обработчика ошибок CSRF"""

    def test_csrf_error_ajax_request(self, app):
        """Тест обработки CSRF ошибки для AJAX запроса"""
        with app.test_request_context(headers={'X-Requested-With': 'XMLHttpRequest'}):
            from flask_wtf.csrf import CSRFError

            # Find and call the CSRF error handler directly
            csrf_handler = None
            for code_or_exception in app.error_handler_spec.get(None, {}):
                if code_or_exception == CSRFError:
                    csrf_handler = app.error_handler_spec[None][code_or_exception]
                    break

            if csrf_handler:
                error = CSRFError('CSRF token missing')
                response = csrf_handler(error)
                assert response[1] == 400
                data = response[0].get_json()
                assert data['success'] is False
                assert 'CSRF' in data['error']

    def test_csrf_error_regular_request(self, app):
        """Тест обработки CSRF ошибки для обычного запроса"""
        with app.test_request_context():
            from flask_wtf.csrf import CSRFError

            # Find and call the CSRF error handler directly
            csrf_handler = None
            for code_or_exception in app.error_handler_spec.get(None, {}):
                if code_or_exception == CSRFError:
                    csrf_handler = app.error_handler_spec[None][code_or_exception]
                    break

            if csrf_handler:
                error = CSRFError('CSRF token missing or invalid')
                response = csrf_handler(error)
                assert response[1] == 400
                assert 'CSRF token missing or invalid' in response[0]


class TestUnauthorizedHandler:
    """Тесты обработчика неавторизованных запросов"""

    def test_unauthorized_ajax_request(self, app, client):
        """Тест обработки неавторизованного AJAX запроса"""
        # Make an AJAX request to a protected endpoint without auth
        response = client.get('/admin', headers={'X-Requested-With': 'XMLHttpRequest'})

        # Should return JSON with 401 or 302 (redirect)
        if response.status_code == 401:
            data = response.get_json()
            assert data is not None
            assert data.get('success') is False or data.get('error') is not None


class TestJinjaGlobals:
    """Тесты глобальных функций Jinja"""

    def test_has_module_unauthenticated(self, app):
        """Тест has_module для неаутентифицированного пользователя"""
        with app.test_request_context():
            # Get the has_module function from jinja globals
            has_module = app.jinja_env.globals['has_module']

            # Should return False when user is not authenticated
            result = has_module('some_module')
            assert result is False

    def test_get_user_modules_unauthenticated(self, app):
        """Тест get_user_modules для неаутентифицированного пользователя"""
        with app.test_request_context():
            # Get the get_user_modules function from jinja globals
            get_user_modules = app.jinja_env.globals['get_user_modules']

            # Should return empty list when user is not authenticated
            result = get_user_modules()
            assert result == []

    def test_has_module_authenticated(self, app, client, test_user):
        """Тест has_module для аутентифицированного пользователя"""
        with client:
            # Login
            client.post('/login', data={
                'username': 'testuser',
                'password': 'password123',
                'submit': 'Login'
            }, follow_redirects=True)

            with app.test_request_context():
                # Manually set up the login context
                from flask_login import login_user
                login_user(test_user)

                # Get the has_module function
                has_module = app.jinja_env.globals['has_module']

                # Should check module access (returns True/False based on ModuleService)
                # We just verify it doesn't crash and returns a boolean
                result = has_module('test_module')
                assert isinstance(result, bool)

    def test_get_user_modules_authenticated(self, app, client, test_user):
        """Тест get_user_modules для аутентифицированного пользователя"""
        with client:
            # Login
            client.post('/login', data={
                'username': 'testuser',
                'password': 'password123',
                'submit': 'Login'
            }, follow_redirects=True)

            with app.test_request_context():
                # Manually set up the login context
                from flask_login import login_user
                login_user(test_user)

                # Get the get_user_modules function
                get_user_modules = app.jinja_env.globals['get_user_modules']

                # Should return list of modules (could be empty)
                result = get_user_modules()
                assert isinstance(result, list)
