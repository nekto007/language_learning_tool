"""
Tests for request ID middleware.
"""
import logging
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

    def test_incoming_valid_request_id_is_reused(self, client):
        """A valid 32-char hex X-Request-ID in the request is echoed back."""
        incoming_id = 'abcdef1234567890abcdef1234567890'
        response = client.get('/', headers={'X-Request-ID': incoming_id})
        assert response.headers.get('X-Request-ID') == incoming_id

    def test_incoming_uppercase_request_id_is_preserved(self, client):
        """A valid 32-char UPPERCASE hex id is preserved, keeping cross-service
        traces linked (audit E-085) — case-insensitive match."""
        incoming_id = 'ABCDEF1234567890ABCDEF1234567890'
        response = client.get('/', headers={'X-Request-ID': incoming_id})
        assert response.headers.get('X-Request-ID') == incoming_id

    @pytest.mark.parametrize('bad_id', [
        'not-a-uuid',
        '',
        'abcdef' * 7,  # 42 chars — too long
        'abcdef',      # too short
        '<script>alert(1)</script>',
        'abcdef1234567890abcdef123456789Z',  # non-hex char Z
    ])
    def test_incoming_invalid_request_id_is_replaced(self, client, bad_id):
        """A non-hex or wrong-length X-Request-ID is replaced with a fresh UUID."""
        headers = {'X-Request-ID': bad_id} if bad_id else {}
        response = client.get('/', headers=headers)
        returned = response.headers.get('X-Request-ID', '')
        assert returned != bad_id, f"Should have replaced invalid id: {bad_id!r}"
        assert len(returned) == 32
        assert all(c in '0123456789abcdef' for c in returned)

    def test_request_id_filter_sets_attribute_in_request_context(self, app):
        """RequestIdFilter injects g.request_id into log records during requests."""
        from app.middleware.request_id import RequestIdFilter
        from flask import g

        filter_obj = RequestIdFilter()
        test_id = 'abc123def456abc123def456abc123de'
        with app.test_request_context('/'):
            g.request_id = test_id
            record = logging.LogRecord(
                name='test', level=logging.INFO, pathname='', lineno=0,
                msg='test message', args=(), exc_info=None,
            )
            filter_obj.filter(record)
            assert record.request_id == test_id

    def test_request_id_filter_defaults_when_no_request_id_on_g(self, app):
        """RequestIdFilter uses '-' when g does not have request_id set."""
        from app.middleware.request_id import RequestIdFilter
        from flask import g

        filter_obj = RequestIdFilter()
        with app.test_request_context('/'):
            # Clear any request_id carried over from the shared app context
            # (the autouse fixture reuses the same app context across tests).
            try:
                del g.request_id
            except AttributeError:
                pass
            record = logging.LogRecord(
                name='test', level=logging.INFO, pathname='', lineno=0,
                msg='test message', args=(), exc_info=None,
            )
            filter_obj.filter(record)
            assert hasattr(record, 'request_id')
            assert record.request_id == '-'

    def test_request_id_filter_attached_to_root_logger(self, app):
        """After add_request_id, root logger handlers carry RequestIdFilter."""
        from app.middleware.request_id import RequestIdFilter

        root_handlers = logging.getLogger().handlers
        app_filters = list(app.logger.filters)
        all_filters = app_filters + [f for h in root_handlers for f in h.filters]
        assert any(isinstance(f, RequestIdFilter) for f in all_filters), (
            "RequestIdFilter not found on root logger handlers or app logger"
        )
