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
    FEEDBACK_PRIORITIES,
    FeedbackReply,
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

    urgent = str(source.get('urgent') or '').strip().lower() in ('1', 'true', 'yes', 'on')

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
    screenshot_reject_reason: Optional[str] = None
    upload = request.files.get('screenshot') if request.files else None
    if upload is not None and getattr(upload, 'filename', ''):
        try:
            screenshot_rel, screenshot_reject_reason = save_feedback_screenshot(upload)
        except Exception:
            logger.warning('feedback_screenshot_save_failed', exc_info=True)
            screenshot_rel, screenshot_reject_reason = None, 'process_failed'

    priority = 'high' if urgent or (category == 'bug' and screenshot_rel) else 'normal'

    try:
        row = create_feedback(
            user_id=current_user.id,
            category=category,
            message=message,
            url=url_value,
            user_agent=user_agent,
            priority=priority,
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
        'feedback_submitted id=%s user_id=%s category=%s has_screenshot=%s screenshot_rejected=%s',
        row.id, current_user.id, category, bool(screenshot_rel), screenshot_reject_reason or '',
    )
    from app.feedback.storage import SCREENSHOT_REJECT_REASONS

    if screenshot_reject_reason:
        screenshot_status = 'rejected'
        screenshot_message = SCREENSHOT_REJECT_REASONS.get(
            screenshot_reject_reason,
            'Скриншот отклонён.',
        )
    elif screenshot_rel:
        screenshot_status = 'attached'
        screenshot_message = None
    else:
        screenshot_status = 'skipped'
        screenshot_message = None

    return jsonify({
        'success': True,
        'id': row.id,
        'thread_url': url_for('feedback.thread_view', feedback_id=row.id),
        'screenshot_status': screenshot_status,
        'screenshot_message': screenshot_message,
        'screenshot_reject_reason': screenshot_reject_reason,
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
        was_resolved = row.status == 'resolved'
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
                _notify_admins_of_reply(row, reply, reopened=was_resolved)
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
    """Single-thread page — owner or admin only.

    Marks all unread ``feedback`` notifications linked to this thread as
    read on open, so the FAB / bell badge counters clear immediately.
    """
    row = Feedback.query.get_or_404(feedback_id)
    if row.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    try:
        from app.notifications.models import Notification

        thread_link = url_for('feedback.thread_view', feedback_id=row.id)
        updated = (
            Notification.query
            .filter(
                Notification.user_id == current_user.id,
                Notification.type == 'feedback',
                Notification.link == thread_link,
                Notification.read.is_(False),
            )
            .update({'read': True}, synchronize_session=False)
        )
        if updated:
            db.session.commit()
    except Exception:
        db.session.rollback()
        logger.warning('feedback_mark_read_failed thread=%s', feedback_id, exc_info=True)

    return render_template(
        'feedback/thread.html',
        feedback=row,
        replies=row.replies,
        is_admin_view=False,
    )


@feedback_bp.route('/api/feedback/threads', methods=['GET'])
@login_required
def thread_list_api():
    """Recent threads for the FAB popup. Owner-only (excludes admin view)."""
    from app.notifications.models import Notification

    try:
        requested_limit = int(request.args.get('limit', 5) or 5)
    except (TypeError, ValueError):
        requested_limit = 5
    limit = max(1, min(requested_limit, 20))
    rows = (
        Feedback.query
        .filter(Feedback.user_id == current_user.id)
        .order_by(Feedback.updated_at.desc())
        .limit(limit)
        .all()
    )

    if not rows:
        return jsonify({'success': True, 'threads': []})

    # Unread badge per thread = unread feedback notifications matching the
    # thread URL. Batch the lookup so we don't N+1 the notifications table.
    links = {
        row.id: url_for('feedback.thread_view', feedback_id=row.id)
        for row in rows
    }
    unread_rows = (
        db.session.query(Notification.link, db.func.count(Notification.id))
        .filter(
            Notification.user_id == current_user.id,
            Notification.type == 'feedback',
            Notification.read.is_(False),
            Notification.link.in_(list(links.values())),
        )
        .group_by(Notification.link)
        .all()
    )
    unread_by_link = {link: int(cnt) for link, cnt in unread_rows}

    row_ids = [row.id for row in rows]
    last_reply_ids = (
        db.session.query(
            FeedbackReply.feedback_id,
            db.func.max(FeedbackReply.id).label('last_reply_id'),
        )
        .filter(FeedbackReply.feedback_id.in_(row_ids))
        .group_by(FeedbackReply.feedback_id)
        .subquery()
    )
    last_replies = (
        db.session.query(FeedbackReply)
        .join(last_reply_ids, FeedbackReply.id == last_reply_ids.c.last_reply_id)
        .all()
    )
    last_reply_by_feedback = {reply.feedback_id: reply for reply in last_replies}

    threads = []
    for row in rows:
        last_reply = last_reply_by_feedback.get(row.id)
        if last_reply is not None:
            preview = last_reply.body
            last_is_admin = bool(last_reply.is_admin)
            last_at = last_reply.created_at
        else:
            preview = row.message
            last_is_admin = False
            last_at = row.created_at
        if preview and len(preview) > 140:
            preview = preview[:140] + '…'
        threads.append({
            'id': row.id,
            'url': links[row.id],
            'category': row.category,
            'status': row.status,
            'priority': row.priority,
            'preview': preview,
            'last_at': last_at.isoformat() if last_at else None,
            'last_is_admin': last_is_admin,
            'unread': unread_by_link.get(links[row.id], 0),
        })
    return jsonify({'success': True, 'threads': threads})


@feedback_bp.route('/api/feedback/unread-count', methods=['GET'])
@login_required
def unread_count():
    """Number of unread admin-reply notifications for the FAB badge.

    Counts in-app ``Notification(type='feedback', read=False)`` rows for
    the current user. Admins also see a count of incoming feedback
    submissions / replies from users via the same notification fan-out,
    so the FAB badge mirrors what's in the bell dropdown — one signal,
    one source of truth.
    """
    from app.notifications.models import Notification

    count = (
        Notification.query
        .filter(
            Notification.user_id == current_user.id,
            Notification.type == 'feedback',
            Notification.read.is_(False),
        )
        .count()
    )
    return jsonify({'success': True, 'count': int(count)})


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
    response = send_file(abs_path, conditional=True)
    response.cache_control.private = True
    response.cache_control.max_age = 3600
    return response


_CATEGORY_LABELS = {'bug': 'Баг', 'idea': 'Идея', 'question': 'Вопрос'}
_CATEGORY_ICONS = {'bug': '🐞', 'idea': '💡', 'question': '❓'}


def _notify_admins_of_feedback(feedback_row) -> None:
    """Fan out an in-app notification + Telegram ping to every admin user."""
    from app.auth.models import User
    from app.notifications.services import create_notification

    label = _CATEGORY_LABELS.get(feedback_row.category, feedback_row.category)
    icon = _CATEGORY_ICONS.get(feedback_row.category, '🔔')
    preview = feedback_row.message[:120]
    if len(feedback_row.message) > 120:
        preview += '…'

    admins = User.query.filter(User.is_admin.is_(True), User.active.is_(True)).all()
    detail_path = url_for('feedback_admin.feedback_detail', feedback_id=feedback_row.id)
    for admin in admins:
        create_notification(
            user_id=admin.id,
            type='feedback',
            title=f'Новая обратная связь: {label}',
            message=preview,
            link=detail_path,
            icon=icon,
        )

    _send_admin_telegram(
        admins,
        title=f'{icon} <b>Новая обратная связь</b>: {label}',
        body=feedback_row.message,
        author=feedback_row.user,
        detail_path=detail_path,
    )


def _notify_admins_of_reply(feedback_row, reply, *, reopened: bool = False) -> None:
    """Fan out an in-app notification + Telegram ping on a user reply."""
    from app.auth.models import User
    from app.notifications.services import create_notification

    preview = reply.body[:120]
    if len(reply.body) > 120:
        preview += '…'

    admins = User.query.filter(User.is_admin.is_(True), User.active.is_(True)).all()
    detail_path = url_for('feedback_admin.feedback_detail', feedback_id=feedback_row.id)
    title = (
        f'Переоткрыто обращение #{feedback_row.id}'
        if reopened else f'Ответ в обратной связи #{feedback_row.id}'
    )
    icon = '🔄' if reopened else '💬'
    for admin in admins:
        create_notification(
            user_id=admin.id,
            type='feedback',
            title=title,
            message=preview,
            link=detail_path,
            icon=icon,
        )

    _send_admin_telegram(
        admins,
        title=(
            f'🔄 <b>Переоткрыто обращение #{feedback_row.id}</b>'
            if reopened else f'💬 <b>Ответ в обращении #{feedback_row.id}</b>'
        ),
        body=reply.body,
        author=reply.author,
        detail_path=detail_path,
    )


def _send_admin_telegram(admins, *, title: str, body: str, author, detail_path: str) -> None:
    """Best-effort Telegram fan-out to admins linked to the bot.

    Quiet on missing bot token, missing TelegramUser link, or HTTP errors —
    the in-app notification path is the authoritative channel; Telegram is
    a convenience push so the operator notices new tickets without sitting
    on the dashboard. Failures here MUST NOT block the feedback save.
    """
    try:
        from flask import current_app, has_request_context, request

        from app.telegram.bot import send_message
        from app.telegram.models import TelegramUser

        admin_ids = [a.id for a in admins if a is not None]
        if not admin_ids:
            return

        links = (
            TelegramUser.query
            .filter(
                TelegramUser.user_id.in_(admin_ids),
                TelegramUser.is_active.is_(True),
                TelegramUser.telegram_id.isnot(None),
            )
            .all()
        )
        if not links:
            return

        # Build an absolute URL when possible — Telegram opens links in
        # external browser; relative paths render unclickable.
        absolute_url = detail_path
        try:
            if has_request_context():
                absolute_url = request.url_root.rstrip('/') + detail_path
            else:
                site_url = current_app.config.get('SITE_URL')
                if site_url:
                    absolute_url = site_url.rstrip('/') + detail_path
        except Exception:
            pass

        author_label = (
            f'{getattr(author, "username", None) or "—"} '
            f'(id={getattr(author, "id", None) or "—"})'
        )
        preview = (body or '').strip()
        if len(preview) > 600:
            preview = preview[:600] + '…'
        # Escape HTML special chars in user-provided text to keep parse_mode=HTML safe.
        import html as _html
        preview = _html.escape(preview)
        author_label = _html.escape(author_label)

        text = (
            f'{title}\n'
            f'От: {author_label}\n\n'
            f'{preview}\n\n'
            f'<a href="{_html.escape(absolute_url)}">Открыть в админке →</a>'
        )

        for link in links:
            try:
                send_message(int(link.telegram_id), text, parse_mode='HTML')
            except Exception:
                logger.warning(
                    'feedback_telegram_send_failed user_id=%s', link.user_id, exc_info=True,
                )
    except Exception:
        logger.warning('feedback_telegram_fanout_failed', exc_info=True)


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
