"""
JWT Authentication utilities for API endpoints

SECURITY: Implements proper token-based authentication for mobile/API clients
instead of relying on CSRF-exempt endpoints.

Features:
- Access tokens (short-lived, 15 min)
- Refresh tokens (long-lived, 30 days)
- Token revocation support
- User identity management
"""
from datetime import timedelta
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    get_jwt,
    jwt_required
)


def create_tokens_for_user(user):
    """
    Create access and refresh tokens for a user

    Args:
        user: User model instance

    Returns:
        dict: {
            'access_token': str,
            'refresh_token': str,
            'expires_in': int (seconds)
        }
    """
    # Additional claims for the token
    additional_claims = {
        'user_id': user.id,
        'username': user.username,
        'is_admin': user.is_admin if hasattr(user, 'is_admin') else False
    }

    # Create tokens
    access_token = create_access_token(
        identity=str(user.id),
        additional_claims=additional_claims,
        fresh=True  # Mark as fresh for sensitive operations
    )

    refresh_token = create_refresh_token(
        identity=str(user.id),
        additional_claims={'username': user.username}
    )

    return {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'token_type': 'Bearer',
        'expires_in': 900  # 15 minutes in seconds
    }


def get_current_user_id():
    """
    Get the current user ID from the JWT token

    Returns:
        int: User ID from token
    """
    return get_jwt_identity()


def get_current_user_claims():
    """
    Get additional claims from the JWT token

    Returns:
        dict: Additional claims from token
    """
    return get_jwt()


def is_token_fresh():
    """
    Check if the current token is fresh (recently issued)

    Fresh tokens are required for sensitive operations like password changes.

    Returns:
        bool: True if token is fresh
    """
    jwt_data = get_jwt()
    return jwt_data.get('fresh', False)


def refresh_access_token():
    """
    Create a new access token from a refresh token

    Must be called from an endpoint decorated with @jwt_required(refresh=True)

    Returns:
        dict: New access token
    """
    current_user_id = get_jwt_identity()
    current_claims = get_jwt()

    # Ensure user_id is a string for JWT identity
    if not isinstance(current_user_id, str):
        current_user_id = str(current_user_id)

    # Create new access token (not fresh, from refresh token)
    access_token = create_access_token(
        identity=current_user_id,
        additional_claims={
            'user_id': current_user_id,
            'username': current_claims.get('username'),
            'is_admin': current_claims.get('is_admin', False)
        },
        fresh=False
    )

    return {
        'access_token': access_token,
        'token_type': 'Bearer',
        'expires_in': 900
    }