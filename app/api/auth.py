import functools
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_user

from app import csrf
from app.auth.models import User
from app.utils.db import db

api_auth = Blueprint('api_auth', __name__)


def api_login_required(f):
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


@api_auth.route('/login', methods=['POST'])
@csrf.exempt  # JWT tokens don't require CSRF protection
def api_login():
    """
    API login endpoint with JWT token authentication

    SECURITY: Returns JWT access and refresh tokens for stateless authentication
    No CSRF needed as tokens are sent in Authorization header, not cookies

    Rate limits:
    - 5 per minute per username (prevent targeted account brute force)
    - 20 per hour per IP (prevent distributed brute force)

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
    from app import limiter
    from app.utils.rate_limit_helpers import get_username_key
    from app.utils.jwt_auth import create_tokens_for_user

    # Apply rate limiting decorators
    @limiter.limit("5 per minute", key_func=lambda: get_username_key())
    @limiter.limit("20 per hour")
    def _api_login_impl():
        if not request.is_json:
            return jsonify({
                'success': False,
                'error': 'Invalid JSON format',
                'status_code': 400
            }), 400

        try:
            data = request.get_json()
        except Exception:
            return jsonify({
                'success': False,
                'error': 'Invalid JSON format',
                'status_code': 400
            }), 400

        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({
                'success': False,
                'error': 'Missing username or password',
                'status_code': 400
            }), 400

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            # Update last login
            user.last_login = datetime.now(timezone.utc)
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

        return jsonify({
            'success': False,
            'error': 'Invalid credentials',
            'status_code': 401
        }), 401

    return _api_login_impl()


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
        return jsonify({
            'success': False,
            'error': str(e),
            'status_code': 401
        }), 401
