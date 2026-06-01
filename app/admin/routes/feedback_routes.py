"""Admin feedback inbox + thread detail view."""

import logging
import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import desc, func, or_

from app.admin.audit import log_admin_action
from app.admin.utils.decorators import admin_required
from app.api.errors import api_error
from app.auth.models import User
from app.feedback.models import (
    FEEDBACK_CATEGORIES,
    FEEDBACK_PRIORITIES,
    FEEDBACK_STATUSES,
    Feedback,
    FeedbackReply,
    create_reply,
)
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
    priority = (request.args.get('priority') or '').strip().lower()
    assignee = request.args.get('assignee', '', type=str).strip()
    q = (request.args.get('q') or '').strip()
    date_from = _parse_date(request.args.get('date_from', ''))
    date_to = _parse_date(request.args.get('date_to', ''))

    if category and category not in FEEDBACK_CATEGORIES:
        category = ''
    if status and status not in FEEDBACK_STATUSES:
        status = ''
    if priority and priority not in FEEDBACK_PRIORITIES:
        priority = ''

    query = (
        db.session.query(Feedback, User)
        .outerjoin(User, Feedback.user_id == User.id)
        .order_by(desc(Feedback.updated_at))
    )
    if category:
        query = query.filter(Feedback.category == category)
    if status:
        query = query.filter(Feedback.status == status)
    if priority:
        query = query.filter(Feedback.priority == priority)
    if assignee == 'unassigned':
        query = query.filter(Feedback.assignee_admin_id.is_(None))
    elif assignee.isdigit():
        query = query.filter(Feedback.assignee_admin_id == int(assignee))
    if q:
        like = f'%{q}%'
        query = query.filter(
            or_(
                Feedback.message.ilike(like),
                Feedback.url.ilike(like),
                Feedback.user_agent.ilike(like),
                User.email.ilike(like),
                User.username.ilike(like),
            )
        )
    if date_from:
        query = query.filter(Feedback.created_at >= date_from)
    if date_to:
        query = query.filter(Feedback.created_at < date_to + timedelta(days=1))

    offset = (page - 1) * _PER_PAGE
    rows = query.limit(_PER_PAGE + 1).offset(offset).all()
    has_more = len(rows) > _PER_PAGE
    rows = rows[:_PER_PAGE]

    fb_ids = [fb.id for fb, _ in rows]
    reply_counts = {}
    if fb_ids:
        reply_counts = dict(
            db.session.query(FeedbackReply.feedback_id, func.count(FeedbackReply.id))
            .filter(FeedbackReply.feedback_id.in_(fb_ids))
            .group_by(FeedbackReply.feedback_id)
            .all()
        )

    entries = [
        {
            'id': fb.id,
            'created_at': fb.created_at,
            'updated_at': fb.updated_at,
            'category': fb.category,
            'status': fb.status,
            'priority': fb.priority,
            'message': fb.message,
            'url': fb.url,
            'has_screenshot': bool(fb.screenshot_path),
            'user_id': fb.user_id,
            'user_email': user.email if user else None,
            'user_username': user.username if user else None,
            'assignee_username': fb.assignee.username if fb.assignee else None,
            'reply_count': reply_counts.get(fb.id, 0),
        }
        for fb, user in rows
    ]

    counts_by_status = dict(
        db.session.query(Feedback.status, func.count(Feedback.id))
        .group_by(Feedback.status)
        .all()
    )
    counts_by_priority = dict(
        db.session.query(Feedback.priority, func.count(Feedback.id))
        .group_by(Feedback.priority)
        .all()
    )
    admins = (
        User.query
        .filter(User.is_admin.is_(True), User.active.is_(True))
        .order_by(User.username.asc())
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
        priorities=FEEDBACK_PRIORITIES,
        admins=admins,
        filter_category=category,
        filter_status=status,
        filter_priority=priority,
        filter_assignee=assignee,
        filter_q=q,
        filter_date_from=request.args.get('date_from', ''),
        filter_date_to=request.args.get('date_to', ''),
        counts_by_status=counts_by_status,
        counts_by_priority=counts_by_priority,
    )


@feedback_admin_bp.route('/feedback/<int:feedback_id>')
@admin_required
def feedback_detail(feedback_id: int):
    """Full thread view for admins: meta + screenshot + reply form."""
    row = Feedback.query.get_or_404(feedback_id)
    # Auto-mark seen on first admin open so the unread badge clears.
    if row.status == 'new':
        row.status = 'seen'
        db.session.commit()
    return render_template(
        'admin/feedback/detail.html',
        feedback=row,
        replies=row.replies,
        author=row.user,
        statuses=FEEDBACK_STATUSES,
        priorities=FEEDBACK_PRIORITIES,
        admins=(
            User.query
            .filter(User.is_admin.is_(True), User.active.is_(True))
            .order_by(User.username.asc())
            .all()
        ),
    )


@feedback_admin_bp.route('/feedback/<int:feedback_id>/reply', methods=['POST'])
@admin_required
def feedback_reply(feedback_id: int):
    row = Feedback.query.get_or_404(feedback_id)
    body = (request.form.get('body') or '').strip()
    if not body:
        flash('Пустой ответ', 'warning')
        return redirect(url_for('feedback_admin.feedback_detail', feedback_id=feedback_id))

    try:
        reply = create_reply(
            feedback_id=row.id,
            author_user_id=current_user.id,
            body=body,
            is_admin=True,
        )
        # Notify the submitter (best-effort, do not block the commit).
        try:
            from app.feedback.routes import notify_user_of_admin_reply
            notify_user_of_admin_reply(row, reply)
        except Exception:
            logger.exception('feedback_admin_reply_notify_failed id=%s', row.id)
        log_admin_action(
            current_user.id,
            'feedback.reply',
            target_type='feedback',
            target_id=row.id,
        )
        db.session.commit()
        flash('Ответ отправлен', 'success')
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'warning')
    except Exception:
        db.session.rollback()
        logger.exception('feedback_admin_reply_failed id=%s', row.id)
        flash('Не удалось сохранить ответ', 'danger')

    return redirect(url_for('feedback_admin.feedback_detail', feedback_id=feedback_id))


@feedback_admin_bp.route('/feedback/<int:feedback_id>/status', methods=['POST'])
@admin_required
def feedback_set_status(feedback_id: int):
    new_status = (request.form.get('status') or '').strip().lower()
    if new_status not in FEEDBACK_STATUSES:
        return api_error('invalid_status', 'unknown status', 400)

    row = Feedback.query.get(feedback_id)
    if row is None:
        return api_error('not_found', 'feedback not found', 404)

    previous = row.status
    row.status = new_status
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
    # Redirect back to detail if the request originated there, else inbox.
    if request.referrer and re.search(rf'/feedback/{feedback_id}(?:/|$|\?)', request.referrer):
        return redirect(url_for('feedback_admin.feedback_detail', feedback_id=feedback_id))
    return redirect(url_for('feedback_admin.feedback_index',
                            page=request.args.get('page', 1),
                            category=request.args.get('category', ''),
                            status=request.args.get('status', '')))


@feedback_admin_bp.route('/feedback/<int:feedback_id>/triage', methods=['POST'])
@admin_required
def feedback_triage(feedback_id: int):
    priority = (request.form.get('priority') or '').strip().lower()
    assignee_raw = (request.form.get('assignee_admin_id') or '').strip()

    if priority not in FEEDBACK_PRIORITIES:
        return api_error('invalid_priority', 'unknown priority', 400)

    row = Feedback.query.get(feedback_id)
    if row is None:
        return api_error('not_found', 'feedback not found', 404)

    assignee_admin_id = None
    if assignee_raw:
        try:
            assignee_admin_id = int(assignee_raw)
        except ValueError:
            return api_error('invalid_assignee', 'unknown assignee', 400)
        assignee_user = User.query.filter_by(id=assignee_admin_id, is_admin=True).first()
        if assignee_user is None:
            return api_error('invalid_assignee', 'unknown assignee', 400)

    previous = (row.priority, row.assignee_admin_id)
    row.priority = priority
    row.assignee_admin_id = assignee_admin_id
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    log_admin_action(
        current_user.id,
        'feedback.triage',
        target_type='feedback',
        target_id=feedback_id,
    )
    db.session.commit()
    logger.info(
        'feedback_triage_changed id=%s priority=%s->%s assignee=%s->%s by admin=%s',
        feedback_id, previous[0], priority, previous[1], assignee_admin_id, current_user.id,
    )
    flash('Триаж обновлён', 'success')
    return redirect(url_for('feedback_admin.feedback_detail', feedback_id=feedback_id))


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None
