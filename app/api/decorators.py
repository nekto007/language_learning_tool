"""
API Security Decorators

Unified authentication decorator that accepts both JWT Bearer tokens
and Flask-Login session cookies. JWT is checked first; session is the fallback.
"""
import functools
import logging

from flask import g, jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_login import current_user

logger = logging.getLogger(__name__)


def _invalid_token_response():
    return jsonify({
        'success': False,
        'error': 'Invalid or expired token',
        'status_code': 401
    }), 401


def api_auth_required(f):
    """
    Unified API authentication: JWT Bearer first, session cookie fallback.

    - If Authorization: Bearer <token> is present, validates JWT and loads the user.
    - Otherwise falls back to Flask-Login session (current_user).
    - Sets current_user in both paths so endpoint code can use current_user.id uniformly.

    DP-098: the JWT branch issues no session cookie. A stateless API call must
    not turn into a browser session, so instead of login_user() the user is
    published request-scoped via g._login_user -- the very attribute
    flask_login reads current_user from.

    DP-096: the try block covers token parsing only. It used to wrap the
    endpoint body too, so any genuine 500 raised under JWT was reported as
    401 Invalid or expired token.

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
                identity = get_jwt_identity()
            except Exception as exc:
                logger.warning(
                    "JWT verification failed: %s", exc, exc_info=True
                )
                return _invalid_token_response()

            # The identity is signed by us, but a non-numeric sub must not
            # reach filter_by(id=...): in Postgres that is a DataError, i.e.
            # a 500 for a token that is plainly invalid.
            try:
                user_id = int(identity)
            except (TypeError, ValueError):
                logger.warning("JWT identity is not a user id: %r", identity)
                return _invalid_token_response()

            user = db_get_user(user_id)
            if user is None:
                return jsonify({
                    'success': False,
                    'error': 'User not found',
                    'status_code': 401
                }), 401

            # current_user is published for the duration of the handler and
            # unwound afterwards: under an outer pushed app context (tests,
            # CLI, background jobs) g outlives the request, and a user left
            # behind would authenticate the next call with no token at all.
            had_previous = '_login_user' in g
            previous = g._login_user if had_previous else None
            g._login_user = user
            try:
                return f(*args, **kwargs)
            finally:
                if had_previous:
                    g._login_user = previous
                else:
                    g.pop('_login_user', None)

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
