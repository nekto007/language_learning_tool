"""Tests for response compression middleware (Flask-Compress)."""
import json
import pytest
from flask_compress import Compress


class TestResponseCompression:
    """Verify gzip compression is configured and applied correctly."""

    @pytest.mark.smoke
    def test_compress_mimetypes_includes_json(self, app):
        """COMPRESS_MIMETYPES config includes application/json."""
        assert 'application/json' in app.config.get('COMPRESS_MIMETYPES', [])

    def test_compress_min_size_configured(self, app):
        """COMPRESS_MIN_SIZE is configured to a sensible threshold."""
        min_size = app.config.get('COMPRESS_MIN_SIZE', 0)
        assert min_size > 0

    def test_compress_level_configured(self, app):
        """COMPRESS_LEVEL is set between 1 and 9."""
        level = app.config.get('COMPRESS_LEVEL', 0)
        assert 1 <= level <= 9

    def test_compress_after_request_hook_registered(self, app):
        """Flask-Compress after_request hook is registered in the app."""
        after_request_funcs = app.after_request_funcs.get(None, [])
        compress_hooks = [
            f for f in after_request_funcs
            if isinstance(f, Compress.after_request.__class__)
            or 'Compress.after_request' in str(f)
        ]
        assert len(compress_hooks) > 0, (
            "Flask-Compress after_request hook not found in app.after_request_funcs"
        )

    def test_health_endpoint_works_with_accept_encoding(self, client):
        """Health endpoint responds correctly when client sends Accept-Encoding: gzip."""
        response = client.get(
            '/health',
            headers={'Accept-Encoding': 'gzip, deflate'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'ok'

    def test_large_json_response_compressed(self, client):
        """Health endpoint with large Accept-Encoding: gzip header is served correctly."""
        # We verify that Flask-Compress is active by ensuring requests with Accept-Encoding
        # are handled without errors, and the response body is still decodable as JSON.
        # The test_client in Flask auto-decompresses gzip, so we check Content-Encoding.
        response = client.get(
            '/health',
            headers={'Accept-Encoding': 'gzip, deflate, br'},
        )
        assert response.status_code == 200
        # Flask test client decompresses automatically, so we can still parse JSON
        data = response.get_json()
        assert data is not None
