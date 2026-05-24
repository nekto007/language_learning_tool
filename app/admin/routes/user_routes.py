# app/admin/routes/user_routes.py

"""
User Management Routes для административной панели
Маршруты для управления пользователями и статистикой
"""
import csv
import io
import logging
from datetime import UTC, datetime

from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import desc

from app.admin.audit import log_admin_action
from app.admin.services import UserManagementService
from app.admin.utils.decorators import admin_required
from app.admin.utils.request_validators import get_int_arg
from app.auth.models import User
from app.utils.db import db

# Создаем blueprint для user routes
user_bp = Blueprint('user_admin', __name__)

logger = logging.getLogger(__name__)


MAX_USERS_PER_PAGE = 100


def _escape_like(term: str) -> str:
    """Escape SQL LIKE wildcards so user-supplied text is matched literally."""
    return term.replace('\\', '\\\\').replace('%', r'\%').replace('_', r'\_')


@user_bp.route('/users')
@admin_required
def users():
    """Управление пользователями"""
    page = get_int_arg('page', default=1, min_val=1)
    per_page_raw = get_int_arg('per_page', default=20, min_val=1)
    per_page = min(per_page_raw, MAX_USERS_PER_PAGE)
    search = (request.args.get('search') or '').strip()[:120]

    query = User.query

    if search:
        like_pattern = f'%{_escape_like(search)}%'
        query = query.filter(
            User.username.ilike(like_pattern, escape='\\') |
            User.email.ilike(like_pattern, escape='\\')
        )

    pagination = query.order_by(desc(User.last_login).nullslast(), User.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    users = pagination.items
    now = datetime.now(UTC).replace(tzinfo=None)

    return render_template(
        'admin/users.html',
        users=users,
        pagination=pagination,
        search=search,
        per_page=per_page,
        now=now
    )


@user_bp.route('/users/<int:user_id>/toggle_status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    """Активация/деактивация пользователя"""
    result = UserManagementService.toggle_user_status(user_id)

    if result:
        status = "активирован" if result['active'] else "деактивирован"
        action = 'user.activate' if result['active'] else 'user.deactivate'
        log_admin_action(current_user.id, action, target_type='user', target_id=user_id)
        db.session.commit()
        flash(f'Пользователь {result["username"]} успешно {status}.', 'success')
    else:
        flash('Пользователь не найден.', 'danger')

    return redirect(url_for('user_admin.users'))


@user_bp.route('/users/<int:user_id>/toggle_admin', methods=['POST'])
@admin_required
def toggle_admin_status(user_id):
    """Предоставление/отзыв прав администратора"""
    success, message = UserManagementService.toggle_admin_status(user_id, current_user.id)

    if success:
        user_after = User.query.get(user_id)
        action = 'user.grant_admin' if (user_after and user_after.is_admin) else 'user.revoke_admin'
        log_admin_action(current_user.id, action, target_type='user', target_id=user_id)
        db.session.commit()
        flash(f'Права администратора успешно изменены: {message}', 'success')
    else:
        flash(message, 'danger')

    return redirect(url_for('user_admin.users'))


@user_bp.route('/users/<int:user_id>/toggle_mission_plan', methods=['POST'])
@admin_required
def toggle_mission_plan(user_id):
    """Enable/disable mission-based daily plan for a user."""
    result = UserManagementService.toggle_mission_plan(user_id)

    if result:
        state = "включён" if result['use_mission_plan'] else "выключен"
        action = 'user.enable_mission_plan' if result['use_mission_plan'] else 'user.disable_mission_plan'
        log_admin_action(current_user.id, action, target_type='user', target_id=user_id)
        db.session.commit()
        flash(f'Mission-based daily plan для {result["username"]} {state}.', 'success')
    else:
        flash('Пользователь не найден.', 'danger')

    from app.auth.routes import get_safe_redirect_url
    next_url = get_safe_redirect_url(
        request.form.get('next') or request.referrer,
        fallback='user_admin.users'
    )
    return redirect(next_url)


@user_bp.route('/users/<int:user_id>')
@admin_required
def user_detail(user_id):
    """Детальная страница пользователя"""
    detail = UserManagementService.get_user_detail(user_id)
    if not detail:
        flash('Пользователь не найден.', 'danger')
        return redirect(url_for('user_admin.users'))

    return render_template('admin/user_detail.html', detail=detail)


@user_bp.route('/linear-plan/<int:user_id>')
@admin_required
def linear_plan_user_inspector(user_id):
    """Per-user linear plan inspector for admin debugging."""
    from sqlalchemy import desc

    from app.achievements.models import StreakEvent
    from app.admin.audit import log_admin_action
    from app.daily_plan.linear.models import QuizErrorLog
    from app.daily_plan.linear.plan import get_linear_plan
    from app.utils.db import db

    user = User.query.get(user_id)
    if user is None:
        flash('Пользователь не найден.', 'danger')
        return redirect(url_for('user_admin.users'))

    log_admin_action(
        admin_id=current_user.id,
        action='user.linear_plan_inspect',
        target_type='user',
        target_id=user_id,
    )
    db.session.commit()

    plan_payload = None
    plan_error = None
    if user.use_linear_plan:
        try:
            plan_payload = get_linear_plan(user_id, db)
        except Exception as exc:  # noqa: BLE001
            logger.exception('Failed to assemble linear plan for user %s', user_id)
            plan_error = str(exc)
            # Plan assembly may have left the SQLAlchemy session in a
            # pending-rollback state; reset it so the follow-up StreakEvent /
            # QuizErrorLog queries below don't 500 with InvalidRequestError.
            db.session.rollback()

    recent_xp_events = (
        StreakEvent.query
        .filter(StreakEvent.user_id == user_id)
        .filter(StreakEvent.event_type.like('xp_linear%'))
        .order_by(desc(StreakEvent.created_at))
        .limit(20)
        .all()
    )

    recent_errors = (
        QuizErrorLog.query
        .filter(QuizErrorLog.user_id == user_id)
        .order_by(desc(QuizErrorLog.created_at))
        .limit(10)
        .all()
    )

    return render_template(
        'admin/linear_plan_user.html',
        user=user,
        plan_payload=plan_payload,
        plan_error=plan_error,
        recent_xp_events=recent_xp_events,
        recent_errors=recent_errors,
    )


@user_bp.route('/users/export')
@admin_required
def export_users_csv():
    """Export users as CSV with key metrics. Sanitized, limited, audit-logged."""
    from app.admin.utils.export_helpers import _sanitize_csv_cell, MAX_EXPORT_ROWS

    search = request.args.get('search', '')
    rows = UserManagementService.export_users_csv(search=search)
    rows = rows[:MAX_EXPORT_ROWS]

    # Audit log
    current_app.logger.info(
        'CSV user export by admin %s, search=%r, %d records',
        current_user.id, search, len(rows),
    )

    # Streaming CSV response with sanitized cells
    fieldnames = [
        'id', 'username', 'email', 'created_at', 'last_login',
        'active', 'lessons_completed', 'current_streak', 'longest_streak', 'coin_balance',
    ]

    def generate():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        yield buf.getvalue()
        for row in rows:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fieldnames)
            writer.writerow({k: _sanitize_csv_cell(v) for k, v in row.items()})
            yield buf.getvalue()

    return Response(
        generate(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=users_export_{datetime.now(UTC).strftime("%Y-%m-%d")}.csv'},
    )


@user_bp.route('/stats')
@admin_required
def stats():
    """Статистика приложения"""
    stats_data = UserManagementService.get_user_activity_stats(days=30)

    return render_template(
        'admin/stats.html',
        user_registrations=stats_data['user_registrations'],
        user_logins=stats_data['user_logins'],
        user_activity_by_hour=stats_data['user_activity_by_hour']
    )
