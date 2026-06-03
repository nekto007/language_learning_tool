"""Public tracking endpoints for email reminders.

Two routes:

* ``GET /r/o/<token>.gif`` — 1×1 transparent pixel. First hit records
  ``opened_at``, every hit bumps ``open_count``.
* ``GET /r/c/<sig>`` — signed redirect (``itsdangerous`` URLSafeSerializer
  payload of ``{t: token, u: url}``). Verifies signature → looks up the
  ``ReminderLog`` by token → increments ``click_count`` → 302 to target URL.

The signature is mandatory: without it any caller could pass an arbitrary
``u=`` and the tracking endpoint would behave as an open redirect.

Failures are swallowed best-effort — tracking must never break delivery of
the user-visible action (pixel returns 200 anyway; click returns 302 even
if logging fails).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from flask import Blueprint, abort, current_app, redirect, request, send_file
from itsdangerous import BadSignature, URLSafeSerializer

from app.reminders.models import ReminderLog
from app.utils.db import db

logger = logging.getLogger(__name__)

reminder_tracking = Blueprint('reminder_tracking', __name__, url_prefix='/r')

_TRANSPARENT_GIF = bytes([
    0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x01, 0x00, 0x01, 0x00, 0x80, 0x00,
    0x00, 0xff, 0xff, 0xff, 0x00, 0x00, 0x00, 0x21, 0xf9, 0x04, 0x01, 0x00,
    0x00, 0x00, 0x00, 0x2c, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00,
    0x00, 0x02, 0x02, 0x44, 0x01, 0x00, 0x3b,
])

_SERIALIZER_SALT = 'reminder-click-v1'


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt=_SERIALIZER_SALT)


def sign_click(token: str, target_url: str) -> str:
    """Pack ``(token, url)`` into a signed opaque blob for the click URL."""
    return _serializer().dumps({'t': token, 'u': target_url})


def _record_open(token: str) -> None:
    log = ReminderLog.query.filter_by(token=token).first()
    if log is None:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if log.opened_at is None:
        log.opened_at = now
    log.open_count = (log.open_count or 0) + 1
    db.session.commit()


def _record_click(token: str) -> None:
    log = ReminderLog.query.filter_by(token=token).first()
    if log is None:
        return
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if log.clicked_at is None:
        log.clicked_at = now
    log.click_count = (log.click_count or 0) + 1
    # Mirror open as well: a click implies the email was rendered.
    if log.opened_at is None:
        log.opened_at = now
    db.session.commit()


def _no_cache_response(resp):
    """Mail clients aggressively cache images — push them not to."""
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, private, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp


@reminder_tracking.route('/o/<token>.gif')
def track_open(token: str):
    import io
    try:
        _record_open(token)
    except Exception:
        logger.exception('reminder open tracking failed token=%s', token)
        try:
            db.session.rollback()
        except Exception:
            pass

    resp = send_file(
        io.BytesIO(_TRANSPARENT_GIF),
        mimetype='image/gif',
        max_age=0,
    )
    return _no_cache_response(resp)


@reminder_tracking.route('/c/<path:blob>')
def track_click(blob: str):
    try:
        payload = _serializer().loads(blob)
    except BadSignature:
        abort(400, 'Invalid tracking signature')

    token: Optional[str] = payload.get('t') if isinstance(payload, dict) else None
    target: Optional[str] = payload.get('u') if isinstance(payload, dict) else None
    if not target or not isinstance(target, str):
        abort(400, 'Invalid tracking payload')
    if not (target.startswith('http://') or target.startswith('https://')):
        abort(400, 'Invalid redirect target')

    if token:
        try:
            _record_click(token)
        except Exception:
            logger.exception('reminder click tracking failed token=%s', token)
            try:
                db.session.rollback()
            except Exception:
                pass

    return redirect(target, code=302)
