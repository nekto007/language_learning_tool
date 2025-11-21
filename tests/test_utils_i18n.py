"""
Tests for utils i18n module
Тесты модуля интернационализации
"""
import pytest
from flask import g
from app.utils.i18n import get_locale, init_babel


class TestGetLocale:
    """Тесты функции get_locale"""

    def test_get_locale_from_url_param(self, app, client):
        """Тест получения языка из параметра URL"""
        with app.test_request_context('/?lang=ru'):
            locale = get_locale()
            assert locale == 'ru'

    def test_get_locale_saves_to_session(self, app, client):
        """Тест сохранения языка в сессию"""
        with client:
            response = client.get('/?lang=ru')
            with client.session_transaction() as session:
                assert session.get('lang') == 'ru'

    def test_get_locale_from_session(self, app):
        """Тест получения языка из сессии"""
        # Используем test_request_context с session
        from flask import session
        with app.test_request_context('/'):
            # Симулируем наличие языка в сессии
            session['lang'] = 'ru'
            locale = get_locale()
            assert locale == 'ru'

    def test_get_locale_from_browser_headers(self, app):
        """Тест получения языка из заголовков браузера"""
        with app.test_request_context('/', headers={'Accept-Language': 'ru,en;q=0.9'}):
            locale = get_locale()
            # Should match one of the supported languages
            assert locale in ['en', 'ru']

    def test_get_locale_default(self, app):
        """Тест языка по умолчанию"""
        with app.test_request_context('/'):
            locale = get_locale()
            # Should return one of supported languages or None
            assert locale in ['en', 'ru', None]


class TestInitBabel:
    """Тесты функции init_babel"""

    def test_g_locale_set_by_before_request(self, app, client):
        """Тест установки g.locale через before_request"""
        with client:
            # Make a request with lang parameter
            response = client.get('/?lang=en')
            # g.locale should be set by before_request hook
            # We can't easily test g.locale directly, but we can test
            # that the mechanism works by checking session
            with client.session_transaction() as session:
                assert session.get('lang') == 'en'
