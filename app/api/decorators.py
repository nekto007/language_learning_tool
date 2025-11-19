"""
API Security Decorators

SECURITY: These decorators enforce proper authentication patterns
and prevent CSRF vulnerabilities in hybrid cookie/JWT systems.
"""
import functools
from flask import jsonify, request
from flask_login import current_user
from flask_jwt_extended import jwt_required, get_jwt_identity


def jwt_only_endpoint(f):
    """
    Decorator to ensure endpoint ONLY accepts JWT authentication, not cookies

    SECURITY: Prevents CSRF attacks on @csrf.exempt endpoints that might
    accidentally accept cookie-based authentication.

    Use this decorator on all @csrf.exempt endpoints to ensure they are
    truly stateless and don't rely on browser cookies.

    Usage:
        @api.route('/endpoint', methods=['POST'])
        @csrf.exempt
        @jwt_only_endpoint
        @jwt_required()
        def endpoint():
            ...

    Why this is needed:
    - Flask-Login's current_user is populated from session cookies
    - If endpoint uses current_user but has @csrf.exempt, it's vulnerable to CSRF
    - This decorator rejects requests that have session cookies to force JWT usage
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if request has session cookie (indicates cookie-based auth attempt)
        if request.cookies.get('session') or 'session' in request.cookies:
            return jsonify({
                'success': False,
                'error': 'This endpoint only accepts JWT authentication. Please use Authorization header.',
                'status_code': 400
            }), 400

        # Also check if Flask-Login populated current_user from cookies
        # (This means someone is trying to use cookies instead of JWT)
        if current_user.is_authenticated and not request.headers.get('Authorization'):
            return jsonify({
                'success': False,
                'error': 'Cookie-based authentication not allowed. Use JWT token in Authorization header.',
                'status_code': 400
            }), 400

        return f(*args, **kwargs)

    return decorated_function


def api_jwt_required(f):
    """
    Secure JWT-based authentication decorator for API endpoints

    SECURITY:
    - Only accepts JWT tokens (no cookies)
    - Safe to use with @csrf.exempt
    - Provides current_user_id via get_jwt_identity()

    Usage:
        @api.route('/endpoint', methods=['POST'])
        @csrf.exempt  # Safe: JWT is stateless
        @api_jwt_required
        def endpoint():
            user_id = get_jwt_identity()  # Get user ID from JWT
            ...

    This replaces the insecure @api_login_required pattern.
    """
    @functools.wraps(f)
    @jwt_required()
    @jwt_only_endpoint
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)

    return decorated_function


def api_login_required(f):
    """
    DEPRECATED: Use @api_jwt_required instead

    This decorator uses Flask-Login (cookies) which requires CSRF protection.
    For API endpoints, use JWT tokens instead:

    BEFORE (insecure):
        @api.route('/endpoint')
        @csrf.exempt  # DANGER: cookies without CSRF!
        @api_login_required
        def endpoint():
            ...

    AFTER (secure):
        @api.route('/endpoint')
        @csrf.exempt  # Safe: JWT is stateless
        @api_jwt_required
        def endpoint():
            user_id = get_jwt_identity()
            ...
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({
                'success': False,
                'error': 'Authentication required',
                'status_code': 401
            }), 401
        return f(*args, **kwargs)

    return decorated_function
