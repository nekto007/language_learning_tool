"""
Security middleware for Flask application.
Adds security headers to all responses.
"""
import base64
import os

from flask import Flask, g, request


def _generate_nonce() -> str:
    """Generate a cryptographically-random base64 nonce for CSP."""
    return base64.b64encode(os.urandom(16)).decode('ascii')


def add_security_headers(app: Flask):
    """
    Add security headers to all HTTP responses.

    A per-request nonce is generated and stored in Flask's ``g`` object as
    ``g.csp_nonce``.  Templates can reference it via the ``csp_nonce``
    context variable (registered below).  The nonce is included in
    ``script-src`` so that inline ``<script nonce="{{ csp_nonce }}">`` blocks
    are allowed by CSP3-compliant browsers while ``'unsafe-inline'`` remains
    as a fallback for older browsers.
    """

    @app.before_request
    def _set_csp_nonce():
        g.csp_nonce = _generate_nonce()

    @app.context_processor
    def _inject_csp_nonce():
        nonce = getattr(g, 'csp_nonce', '')
        return {'csp_nonce': nonce}

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
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains; preload'
            )

        # Referrer policy for privacy
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        # Content Security Policy
        # 'unsafe-inline' is kept for backward compatibility with the 33+
        # inline <script> blocks that have not yet been migrated to nonces.
        # CSP3-compliant browsers ignore 'unsafe-inline' when a valid nonce
        # is present, so progressive migration is safe.
        nonce = getattr(g, 'csp_nonce', '')
        nonce_src = f"'nonce-{nonce}'" if nonce else ''

        if request.path.startswith('/admin/reminders/preview/'):
            frame_ancestors = "'self'"
        else:
            frame_ancestors = "'none'"

        script_src_parts = [
            "'self'",
            "'unsafe-inline'",
        ]
        if nonce_src:
            script_src_parts.append(nonce_src)
        script_src_parts += [
            'https://cdnjs.cloudflare.com',
            'https://cdn.jsdelivr.net',
            'https://www.googletagmanager.com',
        ]
        script_src = ' '.join(script_src_parts)

        csp_policy = (
            "default-src 'self'; "
            f"script-src {script_src}; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com "
            "https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' data: https://cdnjs.cloudflare.com "
            "https://cdn.jsdelivr.net https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self' https://www.google-analytics.com "
            "https://*.google-analytics.com https://*.analytics.google.com "
            "https://*.googletagmanager.com; "
            "form-action 'self'; "
            f"frame-ancestors {frame_ancestors}; "
            "base-uri 'self'"
        )
        response.headers['Content-Security-Policy'] = csp_policy

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
