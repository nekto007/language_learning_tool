"""Telegram webhook and account linking routes."""
import hmac
import logging
import threading
from collections import deque

from flask import request, jsonify, current_app
from flask_login import login_required, current_user
from app import csrf, limiter
from app.telegram import telegram_bp
from app.telegram.models import TelegramLinkCode, TelegramUser
from app.utils.db import db

logger = logging.getLogger(__name__)


# ── Update-ID deduplication (Telegram retries protection) ───────────

class _BoundedUpdateSet:
    """Thread-safe bounded set for deduplicating Telegram update_ids."""

    def __init__(self, maxlen: int = 1000) -> None:
        self._maxlen = maxlen
        self._queue: deque[int] = deque()
        self._seen: set[int] = set()
        self._lock = threading.Lock()

    def is_duplicate(self, update_id: int) -> bool:
        """Return True if update_id was already seen; register it if not."""
        with self._lock:
            if update_id in self._seen:
                return True
            self._queue.append(update_id)
            self._seen.add(update_id)
            if len(self._queue) > self._maxlen:
                old = self._queue.popleft()
                self._seen.discard(old)
            return False


_update_tracker = _BoundedUpdateSet(maxlen=1000)


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

    # SECURITY: fail-closed — reject if secret not configured
    secret = current_app.config.get('TELEGRAM_WEBHOOK_SECRET')
    if not secret:
        logger.error('TELEGRAM_WEBHOOK_SECRET not configured — rejecting webhook')
        return '', 500

    token = request.headers.get('X-Telegram-Bot-Api-Secret-Token')
    if not token or not hmac.compare_digest(token, secret):
        logger.warning('Webhook request with invalid or missing secret token')
        return '', 403

    data = request.get_json(silent=True)
    if not data:
        return '', 400

    # Idempotency: skip updates Telegram already delivered successfully
    update_id = data.get('update_id')
    if update_id is not None and _update_tracker.is_duplicate(update_id):
        logger.debug('Skipping duplicate Telegram update_id=%s', update_id)
        return '', 200

    try:
        handle_update(data)
    except Exception:
        logger.exception('Error handling Telegram update')

    return '', 200
