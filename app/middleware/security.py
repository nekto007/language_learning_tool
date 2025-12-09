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
        
        # Content Security Policy - restrictive but functional
        # Allow iframe embedding for email template preview routes
        if request.path.startswith('/admin/reminders/preview/'):
            frame_ancestors = "'self'"
        else:
            frame_ancestors = "'none'"

        csp_policy = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
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