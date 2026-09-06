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
    flask_login reads current_user from. login_user()'s own is_active gate is
    reproduced explicitly below; it is the only thing that kept deactivated
    accounts out of the JWT path.

    DP-096: the try block covers token parsing only. It used to wrap the
    endpoint body too, so any genuine 500 raised under JWT was reported as
    401 Invalid or expired token.

    CSRF note: do NOT stack @csrf.exempt on top of this decorator. The session
    fallback means an exempt endpoint is reachable with cookies alone, and a
    cross-site form POST carries remember_token (Flask-Login) from browsers
    without Lax-by-default -- eight daily-plan endpoints were exposed that way
    until 2026-09-01. Browser callers send X-CSRFToken; a future JWT-only
    client would need an exemption gated on the Bearer header, not a blanket
    @csrf.exempt. Guard: tests/security/test_csrf_sweep.py.
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            try:
                verify_jwt_in_request()
                identity = get_jwt_identity()
            except Exception as exc:
                # An expired or malformed token is routine (a stale token in some
                # client), not an incident: one INFO line carrying what is needed
                # to find that client. Anything else keeps the traceback.
                from flask_jwt_extended.exceptions import JWTExtendedException
                from jwt import PyJWTError

                ua = (request.user_agent.string or '')[:120]
                if isinstance(exc, (JWTExtendedException, PyJWTError)):
                    logger.info("JWT rejected: %s path=%s ua=%s", exc, request.path, ua)
                else:
                    logger.warning(
                        "JWT verification failed: %s path=%s ua=%s", exc, request.path, ua, exc_info=True,
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

            # login_user() refused to publish a deactivated account
            # (`if not force and not user.is_active: return False`), and the
            # handler then died on current_user.id. Publishing g._login_user
            # directly has no such guard, so the check must be explicit:
            # /api/auth/refresh does not re-check is_active, and a 30-day
            # refresh token would otherwise outlive deactivation.
            if not user.is_active:
                logger.warning("JWT call by inactive user %s rejected", user_id)
                return jsonify({
                    'success': False,
                    'error': 'Account is inactive',
                    'status_code': 403
                }), 403

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
