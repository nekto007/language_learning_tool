"""Admin feedback inbox — paginated, filterable view over Feedback submissions."""

import logging
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import desc

from app.admin.audit import log_admin_action
from app.admin.utils.decorators import admin_required
from app.api.errors import api_error
from app.auth.models import User
from app.feedback.models import FEEDBACK_CATEGORIES, FEEDBACK_STATUSES, Feedback
from app.utils.db import db

feedback_admin_bp = Blueprint('feedback_admin', __name__)

logger = logging.getLogger(__name__)

_PER_PAGE = 30


@feedback_admin_bp.route('/feedback')
@admin_required
def feedback_index():
    page = max(1, request.args.get('page', 1, type=int))
    category = (request.args.get('category') or '').strip().lower()
    status = (request.args.get('status') or '').strip().lower()
    date_from = _parse_date(request.args.get('date_from', ''))
    date_to = _parse_date(request.args.get('date_to', ''))

    if category and category not in FEEDBACK_CATEGORIES:
        category = ''
    if status and status not in FEEDBACK_STATUSES:
        status = ''

    query = (
        db.session.query(Feedback, User)
        .outerjoin(User, Feedback.user_id == User.id)
        .order_by(desc(Feedback.created_at))
    )
    if category:
        query = query.filter(Feedback.category == category)
    if status:
        query = query.filter(Feedback.status == status)
    if date_from:
        query = query.filter(Feedback.created_at >= date_from)
    if date_to:
        query = query.filter(Feedback.created_at < date_to + timedelta(days=1))

    offset = (page - 1) * _PER_PAGE
    rows = query.limit(_PER_PAGE + 1).offset(offset).all()
    has_more = len(rows) > _PER_PAGE
    rows = rows[:_PER_PAGE]

    entries = [
        {
            'id': fb.id,
            'created_at': fb.created_at,
            'category': fb.category,
            'status': fb.status,
            'message': fb.message,
            'url': fb.url,
            'user_agent': fb.user_agent,
            'user_id': fb.user_id,
            'user_email': user.email if user else None,
            'user_username': user.username if user else None,
        }
        for fb, user in rows
    ]

    counts_by_status = dict(
        db.session.query(Feedback.status, db.func.count(Feedback.id))
        .group_by(Feedback.status)
        .all()
    )

    return render_template(
        'admin/feedback/index.html',
        entries=entries,
        page=page,
        has_more=has_more,
        per_page=_PER_PAGE,
        categories=FEEDBACK_CATEGORIES,
        statuses=FEEDBACK_STATUSES,
        filter_category=category,
        filter_status=status,
        filter_date_from=request.args.get('date_from', ''),
        filter_date_to=request.args.get('date_to', ''),
        counts_by_status=counts_by_status,
    )


@feedback_admin_bp.route('/feedback/<int:feedback_id>/status', methods=['POST'])
@admin_required
def feedback_set_status(feedback_id: int):
    new_status = (request.form.get('status') or '').strip().lower()
    if new_status not in FEEDBACK_STATUSES:
        return api_error('invalid_status', 'unknown status', 400)

    row = Feedback.query.get(feedback_id)
    if row is None:
        return api_error('not_found', 'feedback not found', 404)

    from flask_login import current_user
    previous = row.status
    row.status = new_status
    log_admin_action(
        current_user.id,
        f'feedback.status.{new_status}',
        target_type='feedback',
        target_id=feedback_id,
    )
    db.session.commit()
    logger.info('feedback_status_changed id=%s %s -> %s by admin=%s',
                feedback_id, previous, new_status, current_user.id)
    flash(f'Статус обновлён: {new_status}', 'success')
    return redirect(url_for('feedback_admin.feedback_index',
                            page=request.args.get('page', 1),
                            category=request.args.get('category', ''),
                            status=request.args.get('status', '')))


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None
