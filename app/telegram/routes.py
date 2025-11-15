"""
Telegram Token Management endpoints

SECURITY: Proper token lifecycle management
- Create tokens with expiration and scope
- List user's tokens
- Revoke tokens individually or all at once
- Audit trail for all operations
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app import csrf
from app.auth.models import User
from app.telegram.models import TelegramToken
from app.utils.db import db

telegram_bp = Blueprint('telegram_mgmt', __name__)


@telegram_bp.route('/telegram/tokens', methods=['GET'])
@jwt_required()
def list_tokens():
    """
    List all Telegram tokens for the current user

    Requires: JWT access token

    Response:
        {
            "success": true,
            "tokens": [
                {
                    "id": int,
                    "scope": str,
                    "device_name": str,
                    "created_at": str,
                    "expires_at": str,
                    "last_used_at": str,
                    "revoked": bool,
                    "is_valid": bool
                }
            ]
        }
    """
    user_id = get_jwt_identity()
    tokens = TelegramToken.query.filter_by(user_id=user_id).order_by(TelegramToken.created_at.desc()).all()

    tokens_data = []
    for token in tokens:
        tokens_data.append({
            'id': token.id,
            'token_preview': f"{token.token[:8]}...{token.token[-4:]}",  # Partial token for identification
            'scope': token.scope,
            'device_name': token.device_name,
            'created_at': token.created_at.isoformat(),
            'expires_at': token.expires_at.isoformat(),
            'last_used_at': token.last_used_at.isoformat() if token.last_used_at else None,
            'revoked': token.revoked,
            'revoked_at': token.revoked_at.isoformat() if token.revoked_at else None,
            'is_valid': token.is_valid()
        })

    return jsonify({
        'success': True,
        'tokens': tokens_data,
        'count': len(tokens_data)
    })


@telegram_bp.route('/telegram/tokens', methods=['POST'])
@jwt_required()
@csrf.exempt  # JWT doesn't need CSRF
def create_token():
    """
    Create a new Telegram API token

    Requires: JWT access token

    Request Body:
        {
            "scope": str (optional, default: "read,write"),
            "device_name": str (optional),
            "expires_in_days": int (optional, default: 90)
        }

    Response:
        {
            "success": true,
            "token": str,
            "token_id": int,
            "scope": str,
            "expires_at": str
        }
    """
    from app import limiter

    @limiter.limit("5 per hour")
    def _create_token_impl():
        user_id = get_jwt_identity()

        data = request.get_json() if request.is_json else {}
        scope = data.get('scope', 'read,write')
        device_name = data.get('device_name')
        expires_in_days = data.get('expires_in_days', 90)

        # Validate scope
        valid_scopes = {'read', 'write', 'admin'}
        requested_scopes = set(scope.split(','))
        if not requested_scopes.issubset(valid_scopes):
            return jsonify({
                'success': False,
                'error': f'Invalid scope. Valid scopes: {", ".join(valid_scopes)}',
                'status_code': 400
            }), 400

        # Create token
        user_agent = request.headers.get('User-Agent')
        token_obj = TelegramToken.create_token(
            user_id=user_id,
            scope=scope,
            expires_in_days=expires_in_days,
            device_name=device_name,
            user_agent=user_agent
        )

        return jsonify({
            'success': True,
            'token': token_obj.token,
            'token_id': token_obj.id,
            'scope': token_obj.scope,
            'device_name': token_obj.device_name,
            'expires_at': token_obj.expires_at.isoformat(),
            'message': 'Save this token securely! It won\'t be shown again.'
        })

    return _create_token_impl()


@telegram_bp.route('/telegram/tokens/<int:token_id>', methods=['DELETE'])
@jwt_required()
def revoke_token(token_id):
    """
    Revoke a specific Telegram token

    Requires: JWT access token

    Args:
        token_id: ID of token to revoke

    Response:
        {
            "success": true,
            "message": "Token revoked successfully"
        }
    """
    user_id = get_jwt_identity()

    token = TelegramToken.query.filter_by(id=token_id, user_id=user_id).first()

    if not token:
        return jsonify({
            'success': False,
            'error': 'Token not found',
            'status_code': 404
        }), 404

    if token.revoked:
        return jsonify({
            'success': False,
            'error': 'Token already revoked',
            'status_code': 400
        }), 400

    token.revoke(reason='Revoked by user')

    return jsonify({
        'success': True,
        'message': 'Token revoked successfully'
    })


@telegram_bp.route('/telegram/tokens/revoke-all', methods='POST'])
@jwt_required()
def revoke_all_tokens():
    """
    Revoke all Telegram tokens for the current user

    Requires: JWT access token

    Response:
        {
            "success": true,
            "revoked_count": int,
            "message": "All tokens revoked successfully"
        }
    """
    user_id = get_jwt_identity()

    tokens = TelegramToken.query.filter_by(user_id=user_id, revoked=False).all()
    count = len(tokens)

    TelegramToken.revoke_all_user_tokens(user_id, reason='Revoke all requested by user')

    return jsonify({
        'success': True,
        'revoked_count': count,
        'message': f'Successfully revoked {count} token(s)'
    })