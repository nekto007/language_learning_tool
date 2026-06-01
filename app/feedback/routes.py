"""Public feedback API + user-facing thread views.

- ``POST /api/feedback`` — multipart submission from the in-app widget
  (category, message, optional screenshot, plus client-collected
  page-info meta).
- ``POST /api/feedback/<id>/reply`` — submitting user replies in their
  own thread (admin replies are routed through the admin blueprint).
- ``GET /feedback`` — list of the user's own threads.
- ``GET /feedback/<id>`` — single thread (user + admin messages).
- ``GET /feedback/screenshots/<path>`` — screenshot file, ACL: owner or admin.
"""

import logging
from typing import Optional

from flask import (
    abort, jsonify, render_template, request, send_file, url_for,
)
from flask_login import current_user, login_required

from app import limiter
from app.api.errors import api_error
from app.feedback import feedback_bp
from app.feedback.models import (
    FEEDBACK_CATEGORIES,
    MESSAGE_MAX_LENGTH,
    REPLY_BODY_MAX_LENGTH,
    URL_MAX_LENGTH,
    USER_AGENT_MAX_LENGTH,
    Feedback,
    create_feedback,
    create_reply,
)
from app.feedback.storage import (
    feedback_screenshot_abs_path,
    save_feedback_screenshot,
)
from app.utils.db import db

logger = logging.getLogger(__name__)


def _coerce_int(value) -> Optional[int]:
    if value is None or value == '':
        return None
    try:
        out = int(value)
    except (TypeError, ValueError):
        return None
    if out < 0 or out > 100_000:
        return None
    return out


def _coerce_float(value) -> Optional[float]:
    if value is None or value == '':
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out < 0 or out > 16:
        return None
    return out


def _trim_str(value, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


@feedback_bp.route('/api/feedback', methods=['POST'])
@login_required
@limiter.limit('5 per hour')
def submit_feedback():
    """Receive a feedback submission (JSON or multipart) from the widget."""
    # multipart for screenshot uploads, JSON for the legacy text-only path.
    if request.content_type and 'multipart/form-data' in request.content_type:
        source = request.form
    else:
        source = request.get_json(silent=True) or {}

    category = (source.get('category') or '').strip().lower()
    if category not in FEEDBACK_CATEGORIES:
        return api_error(
            'invalid_category',
            'category must be one of: ' + ', '.join(FEEDBACK_CATEGORIES),
            400,
        )

    message = (source.get('message') or '').strip()
    if not message:
        return api_error('empty_message', 'message is required', 400)
    if len(message) > MESSAGE_MAX_LENGTH:
        message = message[:MESSAGE_MAX_LENGTH]

    url_value = _trim_str(source.get('url'), URL_MAX_LENGTH)
    if not url_value and request.referrer:
        url_value = request.referrer[:URL_MAX_LENGTH]

    user_agent = (request.user_agent.string or '')[:USER_AGENT_MAX_LENGTH] or None

    screenshot_rel: Optional[str] = None
    upload = request.files.get('screenshot') if request.files else None
    if upload is not None and getattr(upload, 'filename', ''):
        try:
            screenshot_rel = save_feedback_screenshot(upload)
        except Exception:
            logger.warning('feedback_screenshot_save_failed', exc_info=True)
            screenshot_rel = None

    try:
        row = create_feedback(
            user_id=current_user.id,
            category=category,
            message=message,
            url=url_value,
            user_agent=user_agent,
            screenshot_path=screenshot_rel,
            viewport_width=_coerce_int(source.get('viewport_width')),
            viewport_height=_coerce_int(source.get('viewport_height')),
            screen_width=_coerce_int(source.get('screen_width')),
            screen_height=_coerce_int(source.get('screen_height')),
            device_pixel_ratio=_coerce_float(source.get('device_pixel_ratio')),
            locale=_trim_str(source.get('locale'), 32),
            timezone=_trim_str(source.get('timezone'), 64),
            platform=_trim_str(source.get('platform'), 64),
        )
        try:
            _notify_admins_of_feedback(row)
        except Exception:
            logger.exception('feedback_notify_failed feedback_id=%s', row.id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('feedback_submit_failed user_id=%s', current_user.id)
        return api_error('save_failed', 'could not save feedback', 500)

    logger.info(
        'feedback_submitted id=%s user_id=%s category=%s has_screenshot=%s',
        row.id, current_user.id, category, bool(screenshot_rel),
    )
    return jsonify({
        'success': True,
        'id': row.id,
        'thread_url': url_for('feedback.thread_view', feedback_id=row.id),
    }), 201


@feedback_bp.route('/api/feedback/<int:feedback_id>/reply', methods=['POST'])
@login_required
@limiter.limit('20 per hour')
def submit_user_reply(feedback_id: int):
    """Submitting user posts a reply to their own thread."""
    row = Feedback.query.get(feedback_id)
    if row is None:
        return api_error('not_found', 'feedback not found', 404)
    if row.user_id != current_user.id and not current_user.is_admin:
        return api_error('forbidden', 'not your feedback thread', 403)

    payload = request.get_json(silent=True) or request.form
    body = (payload.get('body') or '').strip()
    if not body:
        return api_error('empty_body', 'reply body is required', 400)
    if len(body) > REPLY_BODY_MAX_LENGTH:
        body = body[:REPLY_BODY_MAX_LENGTH]

    try:
        reply = create_reply(
            feedback_id=row.id,
            author_user_id=current_user.id,
            body=body,
            is_admin=bool(current_user.is_admin),
        )
        # When the user follows up, notify admins so they see the bump in
        # the inbox. Skip if the author themselves is an admin (avoids
        # self-fan-out).
        if not current_user.is_admin:
            try:
                _notify_admins_of_reply(row, reply)
            except Exception:
                logger.exception('feedback_reply_notify_admins_failed id=%s', row.id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('feedback_reply_failed user_id=%s', current_user.id)
        return api_error('save_failed', 'could not save reply', 500)

    return jsonify({
        'success': True,
        'reply_id': reply.id,
        'created_at': reply.created_at.isoformat(),
    }), 201


@feedback_bp.route('/feedback', methods=['GET'])
@login_required
def my_feedback_list():
    """User's own feedback threads, newest activity first."""
    rows = (
        Feedback.query
        .filter(Feedback.user_id == current_user.id)
        .order_by(Feedback.updated_at.desc())
        .limit(50)
        .all()
    )
    return render_template('feedback/list.html', feedbacks=rows)


@feedback_bp.route('/feedback/<int:feedback_id>', methods=['GET'])
@login_required
def thread_view(feedback_id: int):
    """Single-thread page — owner or admin only."""
    row = Feedback.query.get_or_404(feedback_id)
    if row.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return render_template(
        'feedback/thread.html',
        feedback=row,
        replies=row.replies,
        is_admin_view=False,
    )


@feedback_bp.route('/feedback/screenshots/<path:rel_path>', methods=['GET'])
@login_required
def serve_screenshot(rel_path: str):
    """Serve a feedback screenshot — owner of the thread OR admin only.

    Screenshots may contain private content (chat windows, settings pages,
    half-typed messages) — never link-shareable.
    """
    # Reconstruct full stored path. Stored value uses POSIX-style ``/``;
    # ``rel_path`` from URL is the same minus the ``feedback/`` prefix
    # because the route receives only the portion after that segment.
    stored = f'feedback/{rel_path}'
    row = Feedback.query.filter_by(screenshot_path=stored).first()
    if row is None:
        abort(404)
    if row.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    abs_path = feedback_screenshot_abs_path(stored)
    if abs_path is None:
        abort(404)
    return send_file(abs_path, conditional=True, max_age=3600)


_CATEGORY_LABELS = {'bug': 'Баг', 'idea': 'Идея', 'question': 'Вопрос'}
_CATEGORY_ICONS = {'bug': '🐞', 'idea': '💡', 'question': '❓'}


def _notify_admins_of_feedback(feedback_row) -> None:
    """Fan out an in-app notification to every admin user."""
    from app.auth.models import User
    from app.notifications.services import create_notification

    label = _CATEGORY_LABELS.get(feedback_row.category, feedback_row.category)
    icon = _CATEGORY_ICONS.get(feedback_row.category, '🔔')
    preview = feedback_row.message[:120]
    if len(feedback_row.message) > 120:
        preview += '…'

    admin_ids = [
        r[0] for r in
        User.query.filter_by(is_admin=True).with_entities(User.id).all()
    ]
    for admin_id in admin_ids:
        create_notification(
            user_id=admin_id,
            type='feedback',
            title=f'Новая обратная связь: {label}',
            message=preview,
            link=url_for('feedback_admin.feedback_detail', feedback_id=feedback_row.id),
            icon=icon,
        )


def _notify_admins_of_reply(feedback_row, reply) -> None:
    """Fan out a notification on a user reply so admins see the bump."""
    from app.auth.models import User
    from app.notifications.services import create_notification

    preview = reply.body[:120]
    if len(reply.body) > 120:
        preview += '…'

    admin_ids = [
        r[0] for r in
        User.query.filter_by(is_admin=True).with_entities(User.id).all()
    ]
    for admin_id in admin_ids:
        create_notification(
            user_id=admin_id,
            type='feedback',
            title=f'Ответ в обратной связи #{feedback_row.id}',
            message=preview,
            link=url_for('feedback_admin.feedback_detail', feedback_id=feedback_row.id),
            icon='💬',
        )


def notify_user_of_admin_reply(feedback_row, reply) -> None:
    """Called from the admin blueprint when an admin replies — pings the user."""
    if not feedback_row.user_id:
        return
    from app.notifications.services import create_notification

    preview = reply.body[:120]
    if len(reply.body) > 120:
        preview += '…'

    create_notification(
        user_id=feedback_row.user_id,
        type='feedback',
        title='Ответ на ваше обращение',
        message=preview,
        link=url_for('feedback.thread_view', feedback_id=feedback_row.id),
        icon='💬',
    )
