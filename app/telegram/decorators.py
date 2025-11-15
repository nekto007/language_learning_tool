"""
Telegram API authentication decorators

SECURITY IMPROVEMENTS:
- Checks token expiration
- Validates token scope
- Updates last_used_at for audit trail
- Supports revocation
"""
import functools
from flask import jsonify, request
from app.telegram.models import TelegramToken


def telegram_auth_required(required_scope='read'):
    """
    Decorator to check for valid Telegram API token with scope verification

    SECURITY:
    - Verifies token exists and is not revoked
    - Checks token has not expired
    - Validates token has required scope
    - Updates last_used_at for audit trail

    Args:
        required_scope: Required scope for this endpoint (default: 'read')

    Usage:
        @telegram_auth_required('read')
        def get_data(token, user):
            ...

        @telegram_auth_required('write')
        def update_data(token, user):
            ...
    """
    def decorator(f):
        @functools.wraps(f)
        def decorated_function(*args, **kwargs):
            token_value = request.headers.get('X-Telegram-Token')

            if not token_value:
                return jsonify({
                    'success': False,
                    'error': 'Missing authentication token',
                    'status_code': 401
                }), 401

            # Get valid token (checks expiration and revocation)
            token = TelegramToken.get_valid_token(token_value)

            if not token:
                return jsonify({
                    'success': False,
                    'error': 'Invalid or expired authentication token',
                    'status_code': 401
                }), 401

            # Check scope
            if not token.has_scope(required_scope):
                return jsonify({
                    'success': False,
                    'error': f'Insufficient permissions. Required scope: {required_scope}',
                    'status_code': 403
                }), 403

            # Pass token and user to the route function
            return f(token=token, user=token.user, *args, **kwargs)

        return decorated_function
    return decorator


# Convenience decorators for common scopes
def telegram_read_required(f):
    """Require read scope"""
    return telegram_auth_required('read')(f)


def telegram_write_required(f):
    """Require write scope"""
    return telegram_auth_required('write')(f)


def telegram_admin_required(f):
    """Require admin scope"""
    return telegram_auth_required('admin')(f)