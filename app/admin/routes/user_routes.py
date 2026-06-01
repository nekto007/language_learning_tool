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
from app.admin.utils.request_validators import escape_like, get_int_arg
from app.auth.models import User
from app.utils.db import db

# Создаем blueprint для user routes
user_bp = Blueprint('user_admin', __name__)

logger = logging.getLogger(__name__)


MAX_USERS_PER_PAGE = 100



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
        like_pattern = f'%{escape_like(search)}%'
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
    if user_id == current_user.id:
        flash('Вы не можете деактивировать свой собственный аккаунт.', 'danger')
        return redirect(url_for('user_admin.users'))

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


@user_bp.route('/users/<int:user_id>')
@admin_required
def user_detail(user_id):
    """Детальная страница пользователя"""
    detail = UserManagementService.get_user_detail(user_id)
    if not detail:
        flash('Пользователь не найден.', 'danger')
        return redirect(url_for('user_admin.users'))

    return render_template('admin/user_detail.html', detail=detail)


@user_bp.route('/users/export')
@admin_required
def export_users_csv():
    """Export users as CSV with key metrics. Sanitized, limited, audit-logged."""
    from app.admin.utils.export_helpers import MAX_EXPORT_ROWS, _sanitize_csv_cell

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
        headers={
            'Content-Disposition': f'attachment; filename=users_export_{datetime.now(UTC).strftime("%Y-%m-%d")}.csv',
        },
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
