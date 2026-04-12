"""
API Security Decorators

Unified authentication decorator that accepts both JWT Bearer tokens
and Flask-Login session cookies. JWT is checked first; session is the fallback.
"""
import functools
import logging

from flask import jsonify, request
from flask_login import current_user, login_user
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity

logger = logging.getLogger(__name__)


def api_auth_required(f):
    """
    Unified API authentication: JWT Bearer first, session cookie fallback.

    - If Authorization: Bearer <token> is present, validates JWT and loads the user.
    - Otherwise falls back to Flask-Login session (current_user).
    - Sets current_user in both paths so endpoint code can use current_user.id uniformly.

    CSRF note: endpoints decorated with @csrf.exempt should only be reachable
    via JWT in practice (mobile/external clients). Browser-AJAX endpoints
    keep CSRF protection via Flask-WTF (no @csrf.exempt).
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                verify_jwt_in_request()
                user_id = get_jwt_identity()
                from app.auth.models import User
                user = db_get_user(user_id)
                if user is None:
                    return jsonify({
                        'success': False,
                        'error': 'User not found',
                        'status_code': 401
                    }), 401
                login_user(user, remember=False)
                return f(*args, **kwargs)
            except Exception:
                return jsonify({
                    'success': False,
                    'error': 'Invalid or expired token',
                    'status_code': 401
                }), 401

        if current_user.is_authenticated:
            return f(*args, **kwargs)

        return jsonify({
            'success': False,
            'error': 'Authentication required',
            'status_code': 401
        }), 401

    return decorated_function


def db_get_user(user_id: int):
    from app.auth.models import User
    return User.query.filter_by(id=user_id).first()


api_jwt_required = api_auth_required
api_login_required = api_auth_required
