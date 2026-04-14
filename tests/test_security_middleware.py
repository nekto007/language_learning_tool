"""
Tests for security middleware (app/middleware/security.py)
"""
import pytest
from flask import Flask


class TestSecurityMiddleware:
    """Tests for add_security_headers middleware"""

    @pytest.fixture
    def app_with_security(self):
        """Create a Flask app with security middleware"""
        from app.middleware.security import add_security_headers

        app = Flask(__name__)
        app.config['TESTING'] = True
        app.config['ENV'] = 'testing'

        # Register middleware
        add_security_headers(app)

        @app.route('/test')
        def test_route():
            return 'OK'

        @app.route('/admin/reminders/preview/1')
        def preview_route():
            return 'Preview'

        return app

    def test_x_frame_options_header(self, app_with_security):
        """Test X-Frame-Options is set to DENY"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            assert response.headers.get('X-Frame-Options') == 'DENY'

    def test_x_content_type_options_header(self, app_with_security):
        """Test X-Content-Type-Options is set to nosniff"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            assert response.headers.get('X-Content-Type-Options') == 'nosniff'

    def test_x_xss_protection_header(self, app_with_security):
        """Test X-XSS-Protection is set"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            assert response.headers.get('X-XSS-Protection') == '1; mode=block'

    def test_referrer_policy_header(self, app_with_security):
        """Test Referrer-Policy is set"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            assert response.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'

    def test_permissions_policy_header(self, app_with_security):
        """Test Permissions-Policy is set"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            policy = response.headers.get('Permissions-Policy')
            assert policy is not None
            assert 'camera=()' in policy
            assert 'microphone=()' in policy
            assert 'geolocation=()' in policy

    def test_content_security_policy_header(self, app_with_security):
        """Test Content-Security-Policy is set"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert csp is not None
            assert "default-src 'self'" in csp
            assert "script-src" in csp
            assert "style-src" in csp

    def test_csp_frame_ancestors_none_for_regular_routes(self, app_with_security):
        """Test CSP frame-ancestors is 'none' for regular routes"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert "frame-ancestors 'none'" in csp

    def test_csp_frame_ancestors_self_for_preview_routes(self, app_with_security):
        """Test CSP frame-ancestors is 'self' for preview routes"""
        with app_with_security.test_client() as client:
            response = client.get('/admin/reminders/preview/1')
            csp = response.headers.get('Content-Security-Policy')
            assert "frame-ancestors 'self'" in csp

    def test_hsts_not_set_in_non_production(self, app_with_security):
        """Test HSTS is not set in non-production environment"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            assert response.headers.get('Strict-Transport-Security') is None


class TestSecurityMiddlewareProduction:
    """Tests for security middleware in production environment"""

    @pytest.fixture
    def production_app(self):
        """Create a Flask app configured for production"""
        from app.middleware.security import add_security_headers

        app = Flask(__name__)
        app.config['TESTING'] = True
        app.config['ENV'] = 'production'

        add_security_headers(app)

        @app.route('/test')
        def test_route():
            return 'OK'

        return app

    def test_hsts_set_in_production(self, production_app):
        """Test HSTS is set in production environment"""
        with production_app.test_client() as client:
            response = client.get('/test')
            hsts = response.headers.get('Strict-Transport-Security')
            assert hsts is not None
            assert 'max-age=' in hsts
            assert 'includeSubDomains' in hsts
            assert 'preload' in hsts


class TestCSPDirectives:
    """Tests for Content-Security-Policy directives"""

    @pytest.fixture
    def app_with_security(self):
        """Create a Flask app with security middleware"""
        from app.middleware.security import add_security_headers

        app = Flask(__name__)
        app.config['TESTING'] = True

        add_security_headers(app)

        @app.route('/test')
        def test_route():
            return 'OK'

        return app

    def test_csp_default_src(self, app_with_security):
        """Test CSP default-src directive"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert "default-src 'self'" in csp

    def test_csp_script_src(self, app_with_security):
        """Test CSP script-src directive"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert "script-src 'self'" in csp
            assert 'cdnjs.cloudflare.com' in csp
            assert 'cdn.jsdelivr.net' in csp

    def test_csp_style_src(self, app_with_security):
        """Test CSP style-src directive"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert "style-src 'self'" in csp
            assert "'unsafe-inline'" in csp

    def test_csp_font_src(self, app_with_security):
        """Test CSP font-src directive"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert "font-src 'self'" in csp
            assert 'data:' in csp

    def test_csp_img_src(self, app_with_security):
        """Test CSP img-src directive"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert "img-src 'self'" in csp
            assert 'data:' in csp

    def test_csp_connect_src(self, app_with_security):
        """Test CSP connect-src directive"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert "connect-src 'self'" in csp

    def test_csp_form_action(self, app_with_security):
        """Test CSP form-action directive"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert "form-action 'self'" in csp

    def test_csp_base_uri(self, app_with_security):
        """Test CSP base-uri directive"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            csp = response.headers.get('Content-Security-Policy')
            assert "base-uri 'self'" in csp


class TestPermissionsPolicy:
    """Tests for Permissions-Policy header"""

    @pytest.fixture
    def app_with_security(self):
        """Create a Flask app with security middleware"""
        from app.middleware.security import add_security_headers

        app = Flask(__name__)
        app.config['TESTING'] = True

        add_security_headers(app)

        @app.route('/test')
        def test_route():
            return 'OK'

        return app

    def test_camera_disabled(self, app_with_security):
        """Test camera is disabled"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            policy = response.headers.get('Permissions-Policy')
            assert 'camera=()' in policy

    def test_microphone_disabled(self, app_with_security):
        """Test microphone is disabled"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            policy = response.headers.get('Permissions-Policy')
            assert 'microphone=()' in policy

    def test_geolocation_disabled(self, app_with_security):
        """Test geolocation is disabled"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            policy = response.headers.get('Permissions-Policy')
            assert 'geolocation=()' in policy

    def test_payment_disabled(self, app_with_security):
        """Test payment is disabled"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            policy = response.headers.get('Permissions-Policy')
            assert 'payment=()' in policy

    def test_usb_disabled(self, app_with_security):
        """Test USB is disabled"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            policy = response.headers.get('Permissions-Policy')
            assert 'usb=()' in policy

    def test_bluetooth_disabled(self, app_with_security):
        """Test bluetooth is disabled"""
        with app_with_security.test_client() as client:
            response = client.get('/test')
            policy = response.headers.get('Permissions-Policy')
            assert 'bluetooth=()' in policy
