import logging
import unicodedata
from datetime import UTC, datetime

from flask import Blueprint, jsonify, request

from app import csrf, limiter
from app.api.errors import api_error
from app.auth.models import User
from app.utils.db import db
from app.utils.rate_limit_helpers import get_username_key

logger = logging.getLogger(__name__)

api_auth = Blueprint('api_auth', __name__)


@api_auth.route('/login', methods=['POST'])
@csrf.exempt  # JWT tokens don't require CSRF protection
@limiter.limit("15 per minute", key_func=get_username_key)
@limiter.limit("60 per hour")
def api_login():
    """
    API login endpoint with JWT token authentication

    SECURITY: Returns JWT access and refresh tokens for stateless authentication
    No CSRF needed as tokens are sent in Authorization header, not cookies

    Rate limits:
    - 15 per minute per username (allows retry storms on token expiry)
    - 60 per hour per IP (prevent distributed brute force)

    Request Body:
        {
            "username": str,
            "password": str
        }

    Response:
        {
            "success": true,
            "access_token": str,
            "refresh_token": str,
            "token_type": "Bearer",
            "expires_in": int,
            "user": {
                "id": int,
                "username": str,
                "is_admin": bool
            }
        }
    """
    from app.utils.jwt_auth import create_tokens_for_user

    if not request.is_json:
        return api_error('invalid_json', 'Invalid JSON format', 400)

    try:
        data = request.get_json()
    except Exception:
        return api_error('invalid_json', 'Invalid JSON format', 400)

    if not isinstance(data, dict):
        return api_error('invalid_json', 'JSON body must be an object', 400)

    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return api_error('missing_fields', 'Missing username or password', 400)

    if not isinstance(username, str) or not isinstance(password, str):
        return api_error('invalid_credentials_format', 'Invalid username or password format', 400)

    username = username.strip()
    # The same field accepts a username or an email address. Email support
    # must not widen the 64-character username contract. Only the identity
    # is trimmed; whitespace is part of an existing password.
    if (not username or len(username) > (254 if '@' in username else 64)
            or any(unicodedata.category(char) in ('Cc', 'Cs') for char in username)
            or len(password) > 128
            or any(unicodedata.category(char) == 'Cs' for char in password)):
        return api_error('invalid_credentials_format', 'Invalid username or password format', 400)

    user = User.query.filter_by(username=username).first()
    if user is None and '@' in username:
        from sqlalchemy import func
        user = User.query.filter(func.lower(User.email) == username.lower()).first()
    if user and user.check_password(password):
        if not user.is_active:
            return api_error('account_inactive', 'Account is inactive', 403)

        # Update last login
        user.last_login = datetime.now(UTC)
        db.session.commit()

        # Create JWT tokens
        tokens = create_tokens_for_user(user)

        return jsonify({
            'success': True,
            **tokens,
            'user': {
                'id': user.id,
                'username': user.username,
                'is_admin': user.is_admin if hasattr(user, 'is_admin') else False
            }
        })

    return api_error('invalid_credentials', 'Invalid credentials', 401)


@api_auth.route('/refresh', methods=['POST'])
@csrf.exempt
def refresh():
    """
    Refresh access token using refresh token

    Requires valid refresh token in Authorization header

    Returns:
        New access token with 15-minute expiration
    """
    from flask_jwt_extended import verify_jwt_in_request

    from app.utils.jwt_auth import refresh_access_token

    try:
        # Verify JWT refresh token is present and valid
        verify_jwt_in_request(refresh=True)

        # Generate new access token
        new_token = refresh_access_token()
        return jsonify({
            'success': True,
            **new_token
        })
    except Exception as e:
        logger.error(f'Token refresh error: {e}', exc_info=True)
        return api_error('token_refresh_failed', 'Token refresh failed', 401)
