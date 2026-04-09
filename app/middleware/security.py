"""
Security middleware for Flask application.
Adds security headers to all responses.
"""
from flask import Flask, request


def add_security_headers(app: Flask):
    """
    Add security headers to all HTTP responses.

    Args:
        app (Flask): Flask application instance
    """

    @app.after_request
    def set_security_headers(response):
        """Set security headers on all responses."""

        # Prevent clickjacking attacks
        response.headers['X-Frame-Options'] = 'DENY'

        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'

        # Enable XSS protection (legacy browsers)
        response.headers['X-XSS-Protection'] = '1; mode=block'

        # Force HTTPS in production
        if app.config.get('ENV') == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'

        # Content Security Policy
        # Note: 'unsafe-inline' is required because the app uses 33+ inline
        # <script> blocks across templates. A nonce-based approach would require
        # adding nonce attributes to every inline script tag.
        if request.path.startswith('/admin/reminders/preview/'):
            frame_ancestors = "'self'"
        else:
            frame_ancestors = "'none'"

        csp_policy = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://www.googletagmanager.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' data: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://www.google-analytics.com https://*.google-analytics.com https://*.analytics.google.com https://*.googletagmanager.com; "
            "form-action 'self'; "
            f"frame-ancestors {frame_ancestors}; "
            "base-uri 'self'"
        )
        response.headers['Content-Security-Policy'] = csp_policy
        
        # Referrer policy for privacy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions policy (formerly Feature Policy)
        permissions_policy = (
            "camera=(), "
            "microphone=(), "
            "geolocation=(), "
            "payment=(), "
            "usb=(), "
            "bluetooth=()"
        )
        response.headers['Permissions-Policy'] = permissions_policy
        
        return response
    
    app.logger.info("Security headers middleware initialized")