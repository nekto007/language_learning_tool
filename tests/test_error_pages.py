"""Tests for custom error pages (404, 403, 500)."""
import pytest
from unittest.mock import patch
from werkzeug.exceptions import Forbidden, InternalServerError


class TestErrorPages:
    """Test that error handlers return correct templates and status codes."""

    @pytest.mark.smoke
    def test_404_returns_html(self, client):
        response = client.get('/nonexistent-page-xyz')
        assert response.status_code == 404
        html = response.data.decode('utf-8')
        assert 'Страница не найдена' in html

    def test_404_returns_json_for_api(self, client):
        response = client.get('/api/nonexistent', headers={'Accept': 'application/json'})
        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False
        assert data['error'] == 'Not found'

    def test_404_returns_json_for_xhr(self, client):
        response = client.get('/nonexistent-page', headers={'X-Requested-With': 'XMLHttpRequest'})
        assert response.status_code == 404
        data = response.get_json()
        assert data['success'] is False

    def test_403_handler_html(self, app):
        with app.test_request_context('/forbidden-page'):
            result = app.handle_http_exception(Forbidden())
            rv = app.make_response(result)
        assert rv.status_code == 403
        html = rv.data.decode('utf-8')
        assert 'Доступ запрещён' in html

    def test_403_handler_json(self, app):
        with app.test_request_context('/api/forbidden', headers={'Accept': 'application/json'}):
            result = app.handle_http_exception(Forbidden())
            rv = app.make_response(result)
        assert rv.status_code == 403
        data = rv.get_json()
        assert data['success'] is False
        assert data['error'] == 'Forbidden'

    def test_500_handler_html(self, app):
        with patch('app.admin.main_routes.increment_5xx_counter'):
            with app.test_request_context('/some-page'):
                result = app.handle_http_exception(InternalServerError())
                rv = app.make_response(result)
        assert rv.status_code == 500
        html = rv.data.decode('utf-8')
        assert 'Ошибка сервера' in html

    def test_500_handler_json(self, app):
        with patch('app.admin.main_routes.increment_5xx_counter'):
            with app.test_request_context('/api/something', headers={'Accept': 'application/json'}):
                result = app.handle_http_exception(InternalServerError())
                rv = app.make_response(result)
        assert rv.status_code == 500
        data = rv.get_json()
        assert data['success'] is False
        assert data['error'] == 'Internal server error'
