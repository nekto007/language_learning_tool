"""Telegram webhook and account linking routes."""
import logging

from flask import request, jsonify, current_app
from flask_login import login_required, current_user
from app import csrf, limiter
from app.telegram import telegram_bp
from app.telegram.models import TelegramLinkCode, TelegramUser
from app.utils.db import db

logger = logging.getLogger(__name__)


# ── Account linking API (website side) ──────────────────────────────

@telegram_bp.route('/generate-code', methods=['POST'])
@login_required
@limiter.limit("3 per minute")
def generate_code():
    """Generate a 6-digit code for linking Telegram account."""
    # Check if already linked
    existing = TelegramUser.query.filter_by(user_id=current_user.id).first()
    if existing and existing.is_active:
        return jsonify({'success': False, 'error': 'Telegram уже привязан'}), 400

    link_code = TelegramLinkCode.generate(current_user.id)
    return jsonify({
        'success': True,
        'code': link_code.code,
        'expires_in_minutes': TelegramLinkCode.CODE_TTL_MINUTES,
    })


@telegram_bp.route('/unlink', methods=['POST'])
@login_required
def unlink():
    """Unlink Telegram account."""
    tg_user = TelegramUser.query.filter_by(user_id=current_user.id).first()
    if not tg_user:
        return jsonify({'success': False, 'error': 'Telegram не привязан'}), 400

    db.session.delete(tg_user)
    db.session.commit()
    return jsonify({'success': True})


@telegram_bp.route('/status')
@login_required
def link_status():
    """Get current Telegram link status."""
    tg_user = TelegramUser.query.filter_by(user_id=current_user.id).first()
    if tg_user and tg_user.is_active:
        return jsonify({
            'linked': True,
            'username': tg_user.username,
            'linked_at': tg_user.linked_at.isoformat() if tg_user.linked_at else None,
        })
    return jsonify({'linked': False})


# ── Webhook (Telegram side) ─────────────────────────────────────────

@telegram_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    """Receive updates from Telegram Bot API."""
    from app.telegram.bot import handle_update

    secret = current_app.config.get('TELEGRAM_WEBHOOK_SECRET')
    if secret:
        token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
        if token != secret:
            return '', 403

    data = request.get_json(silent=True)
    if not data:
        return '', 400

    try:
        handle_update(data)
    except Exception:
        logger.exception('Error handling Telegram update')

    return '', 200
