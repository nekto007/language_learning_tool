"""Public feedback API: accepts user-submitted bug reports / ideas / questions."""

import logging

from flask import jsonify, request
from flask_login import current_user, login_required

from app import limiter
from app.api.errors import api_error
from app.feedback import feedback_bp
from app.feedback.models import (
    FEEDBACK_CATEGORIES,
    MESSAGE_MAX_LENGTH,
    URL_MAX_LENGTH,
    USER_AGENT_MAX_LENGTH,
    create_feedback,
)
from app.utils.db import db

logger = logging.getLogger(__name__)


@feedback_bp.route('/api/feedback', methods=['POST'])
@login_required
@limiter.limit('5 per hour')
def submit_feedback():
    """Receive a feedback submission from the in-app widget."""
    payload = request.get_json(silent=True) or {}

    category = (payload.get('category') or '').strip().lower()
    if category not in FEEDBACK_CATEGORIES:
        return api_error(
            'invalid_category',
            'category must be one of: ' + ', '.join(FEEDBACK_CATEGORIES),
            400,
        )

    message = (payload.get('message') or '').strip()
    if not message:
        return api_error('empty_message', 'message is required', 400)
    if len(message) > MESSAGE_MAX_LENGTH:
        message = message[:MESSAGE_MAX_LENGTH]

    url_value = (payload.get('url') or '').strip()[:URL_MAX_LENGTH] or None
    # Prefer the client-reported URL (which may differ from request.referrer if
    # the user navigated within an SPA-ish flow), fall back to Referer header.
    if not url_value and request.referrer:
        url_value = request.referrer[:URL_MAX_LENGTH]

    user_agent = (request.user_agent.string or '')[:USER_AGENT_MAX_LENGTH] or None

    try:
        row = create_feedback(
            user_id=current_user.id,
            category=category,
            message=message,
            url=url_value,
            user_agent=user_agent,
        )
        # Stage in-app notifications for every admin so the bell badge surfaces
        # new feedback immediately. Failure to notify must not block the
        # submission itself — admins can still see the entry on /admin/feedback.
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
        'feedback_submitted id=%s user_id=%s category=%s',
        row.id, current_user.id, category,
    )
    return jsonify({'success': True, 'id': row.id}), 201


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

    admin_ids = [r[0] for r in User.query.filter_by(is_admin=True).with_entities(User.id).all()]
    for admin_id in admin_ids:
        create_notification(
            user_id=admin_id,
            type='feedback',
            title=f'Новая обратная связь: {label}',
            message=preview,
            link='/admin/feedback',
            icon=icon,
        )
