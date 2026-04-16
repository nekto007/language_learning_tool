"""
Tests for request ID middleware.
"""
import pytest


@pytest.fixture(autouse=True)
def _reset_db_session(app):
    from app.utils.db import db
    try:
        db.session.rollback()
    except Exception:
        pass


class TestRequestIdMiddleware:

    @pytest.mark.smoke
    def test_response_includes_x_request_id_header(self, client):
        """Every response must include an X-Request-ID header."""
        response = client.get('/')
        assert 'X-Request-ID' in response.headers

    def test_x_request_id_is_32_char_hex(self, client):
        """X-Request-ID must be a 32-character hex string (uuid4().hex)."""
        response = client.get('/')
        request_id = response.headers.get('X-Request-ID', '')
        assert len(request_id) == 32
        assert all(c in '0123456789abcdef' for c in request_id)

    def test_x_request_id_unique_per_request(self, client):
        """Each request must get a distinct X-Request-ID."""
        r1 = client.get('/')
        r2 = client.get('/')
        id1 = r1.headers.get('X-Request-ID')
        id2 = r2.headers.get('X-Request-ID')
        assert id1 is not None
        assert id2 is not None
        assert id1 != id2

    def test_x_request_id_present_on_api_route(self, client):
        """X-Request-ID header is also present on API/JSON responses."""
        response = client.get('/health')
        assert 'X-Request-ID' in response.headers
