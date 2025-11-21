# app/admin/routes/user_routes.py

"""
User Management Routes для административной панели
Маршруты для управления пользователями и статистикой
"""
import logging
from datetime import UTC, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import desc

from app.admin.services import UserManagementService
from app.admin.utils.decorators import admin_required
from app.auth.models import User

# Создаем blueprint для user routes
user_bp = Blueprint('user_admin', __name__)

logger = logging.getLogger(__name__)


@user_bp.route('/users')
@admin_required
def users():
    """Управление пользователями"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '')

    # Build query with search
    query = User.query

    if search:
        query = query.filter(
            (User.username.ilike(f'%{search}%')) |
            (User.email.ilike(f'%{search}%'))
        )

    # Paginate
    pagination = query.order_by(desc(User.last_login)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    users = pagination.items
    # Use datetime.now(UTC) and convert to naive for DB compatibility
    now = datetime.now(UTC).replace(tzinfo=None)

    return render_template(
        'admin/users.html',
        users=users,
        pagination=pagination,
        search=search,
        now=now
    )


@user_bp.route('/users/<int:user_id>/toggle_status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    """Активация/деактивация пользователя"""
    result = UserManagementService.toggle_user_status(user_id)

    if result:
        status = "активирован" if result['active'] else "деактивирован"
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
        flash(f'Права администратора успешно изменены: {message}', 'success')
    else:
        flash(message, 'danger')

    return redirect(url_for('user_admin.users'))


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
