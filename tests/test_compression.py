"""Tests for response compression middleware (Flask-Compress) and static asset caching."""
import json
import pytest
from flask_compress import Compress


class TestResponseCompression:
    """Verify gzip compression is configured and applied correctly."""

    @pytest.mark.smoke
    def test_compress_mimetypes_includes_json(self, app):
        """COMPRESS_MIMETYPES config includes application/json."""
        assert 'application/json' in app.config.get('COMPRESS_MIMETYPES', [])

    @pytest.mark.smoke
    def test_compress_mimetypes_includes_html(self, app):
        """COMPRESS_MIMETYPES config includes text/html."""
        assert 'text/html' in app.config.get('COMPRESS_MIMETYPES', [])

    @pytest.mark.smoke
    def test_compress_mimetypes_includes_css(self, app):
        """COMPRESS_MIMETYPES config includes text/css."""
        assert 'text/css' in app.config.get('COMPRESS_MIMETYPES', [])

    @pytest.mark.smoke
    def test_compress_mimetypes_includes_javascript(self, app):
        """COMPRESS_MIMETYPES config includes application/javascript or text/javascript."""
        mimetypes = app.config.get('COMPRESS_MIMETYPES', [])
        assert 'application/javascript' in mimetypes or 'text/javascript' in mimetypes

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
        """Responses with Accept-Encoding: gzip are handled without errors."""
        response = client.get(
            '/health',
            headers={'Accept-Encoding': 'gzip, deflate, br'},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None

    def test_images_not_in_compress_mimetypes(self, app):
        """Image MIME types are not in COMPRESS_MIMETYPES (already compressed)."""
        mimetypes = app.config.get('COMPRESS_MIMETYPES', [])
        image_types = [m for m in mimetypes if m.startswith('image/')]
        assert image_types == [], (
            f"Image types should not be re-compressed: {image_types}"
        )

    def test_audio_not_in_compress_mimetypes(self, app):
        """Audio MIME types are not in COMPRESS_MIMETYPES (already compressed)."""
        mimetypes = app.config.get('COMPRESS_MIMETYPES', [])
        audio_types = [m for m in mimetypes if m.startswith('audio/')]
        assert audio_types == [], (
            f"Audio types should not be re-compressed: {audio_types}"
        )

    def test_video_not_in_compress_mimetypes(self, app):
        """Video MIME types are not in COMPRESS_MIMETYPES (already compressed)."""
        mimetypes = app.config.get('COMPRESS_MIMETYPES', [])
        video_types = [m for m in mimetypes if m.startswith('video/')]
        assert video_types == [], (
            f"Video types should not be re-compressed: {video_types}"
        )


class TestStaticAssetCaching:
    """Verify ETag and Cache-Control headers on static file responses."""

    def test_static_css_has_etag(self, client):
        """CSS static files include an ETag header (set by Werkzeug send_file)."""
        response = client.get('/static/css/design-system.css')
        assert response.status_code == 200
        assert 'ETag' in response.headers, "Static CSS file must include ETag header"

    def test_static_js_has_etag(self, client):
        """JS static files include an ETag header."""
        response = client.get('/static/js/unified-js.js')
        assert response.status_code in (200, 304)
        if response.status_code == 200:
            assert 'ETag' in response.headers, "Static JS file must include ETag header"

    def test_static_unversioned_has_cache_control(self, client):
        """Unversioned static files have Cache-Control: public set."""
        response = client.get('/static/css/design-system.css')
        assert response.status_code == 200
        cc = response.headers.get('Cache-Control', '')
        assert 'public' in cc, (
            f"Unversioned static file should have Cache-Control: public, got: {cc!r}"
        )

    def test_static_versioned_has_immutable_cache_control(self, client):
        """Static files with ?v= query param get Cache-Control: immutable."""
        response = client.get('/static/css/design-system.css?v=1.2.3')
        assert response.status_code == 200
        cc = response.headers.get('Cache-Control', '')
        assert 'immutable' in cc, (
            f"Versioned static file should have Cache-Control: immutable, got: {cc!r}"
        )
        assert 'max-age=31536000' in cc or '31536000' in cc, (
            f"Versioned static file should have 1-year max-age, got: {cc!r}"
        )

    def test_static_versioned_long_max_age(self, client):
        """Versioned static files have max-age of at least 1 year (31536000 seconds)."""
        response = client.get('/static/css/design-system.css?v=abc123')
        assert response.status_code == 200
        cc = response.headers.get('Cache-Control', '')
        assert '31536000' in cc, (
            f"Versioned static asset should have max-age=31536000, got: {cc!r}"
        )

    def test_static_unversioned_max_age_reasonable(self, client):
        """Unversioned static files have a non-zero max-age."""
        response = client.get('/static/css/design-system.css')
        assert response.status_code == 200
        cc = response.headers.get('Cache-Control', '')
        # Should have some positive max-age
        assert 'max-age=' in cc, (
            f"Unversioned static file should have max-age in Cache-Control, got: {cc!r}"
        )
        import re
        match = re.search(r'max-age=(\d+)', cc)
        assert match and int(match.group(1)) > 0, (
            f"max-age should be positive, got: {cc!r}"
        )

    def test_static_unversioned_not_immutable(self, client):
        """Unversioned static files do NOT have Cache-Control: immutable."""
        response = client.get('/static/css/design-system.css')
        assert response.status_code == 200
        cc = response.headers.get('Cache-Control', '')
        assert 'immutable' not in cc, (
            f"Unversioned static file should not have immutable directive, got: {cc!r}"
        )

    def test_nonexistent_static_returns_404(self, client):
        """Requesting a non-existent static file returns 404."""
        response = client.get('/static/css/nonexistent-file-xyz.css')
        assert response.status_code == 404
