# app/admin/routes/user_routes.py

"""
User Management Routes для административной панели
Маршруты для управления пользователями и статистикой
"""
import csv
import io
import logging
from datetime import UTC, date, datetime, timedelta

from flask import Blueprint, Response, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import asc, desc, func

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
VALID_PLAN_DIFFICULTIES = {'light', 'normal', 'intensive'}
VALID_ONBOARDING_LEVELS = {'', 'A1', 'A2', 'B1', 'B2', 'C1'}



@user_bp.route('/users')
@admin_required
def users():
    """Управление пользователями"""
    page = get_int_arg('page', default=1, min_val=1)
    per_page_raw = get_int_arg('per_page', default=20, min_val=1)
    per_page = min(per_page_raw, MAX_USERS_PER_PAGE)
    search = (request.args.get('search') or '').strip()[:120]
    status = (request.args.get('status') or 'all').strip()
    role = (request.args.get('role') or 'all').strip()
    email_state = (request.args.get('email_state') or 'all').strip()
    activity = (request.args.get('activity') or 'all').strip()
    sort = (request.args.get('sort') or 'last_login').strip()
    now = datetime.now(UTC).replace(tzinfo=None)

    query = User.query

    if search:
        like_pattern = f'%{escape_like(search)}%'
        query = query.filter(
            User.username.ilike(like_pattern, escape='\\') |
            User.email.ilike(like_pattern, escape='\\')
        )

    if status == 'active':
        query = query.filter(User.active.is_(True))
    elif status == 'inactive':
        query = query.filter(User.active.is_(False))

    if role == 'admin':
        query = query.filter(User.is_admin.is_(True))
    elif role == 'user':
        query = query.filter(User.is_admin.is_(False))

    if email_state == 'ready':
        query = query.filter(
            User.email.isnot(None),
            User.email_opted_out.is_(False),
            User.notify_email_reminders.is_(True),
        )
    elif email_state == 'opted_out':
        query = query.filter(User.email_opted_out.is_(True))
    elif email_state == 'disabled':
        query = query.filter(User.notify_email_reminders.is_(False))
    elif email_state == 'no_email':
        query = query.filter(db.or_(User.email.is_(None), User.email == ''))

    if activity == 'active_7':
        query = query.filter(User.last_login >= now - timedelta(days=7))
    elif activity == 'inactive_7':
        cutoff = now.replace(tzinfo=None) - timedelta(days=7)
        query = query.filter(db.or_(User.last_login.is_(None), User.last_login < cutoff))
    elif activity == 'inactive_30':
        cutoff = now.replace(tzinfo=None) - timedelta(days=30)
        query = query.filter(db.or_(User.last_login.is_(None), User.last_login < cutoff))
    elif activity == 'never':
        query = query.filter(User.last_login.is_(None))

    sort_map = {
        'created': (desc(User.created_at), User.id.desc()),
        'username': (asc(func.lower(User.username)), User.id.desc()),
        'inactive': (asc(User.last_login).nullsfirst(), User.id.desc()),
        'last_login': (desc(User.last_login).nullslast(), User.id.desc()),
    }
    order_by = sort_map.get(sort, sort_map['last_login'])

    pagination = query.order_by(*order_by).paginate(
        page=page, per_page=per_page, error_out=False
    )

    users_page = pagination.items
    user_ids = [u.id for u in users_page]
    stats_by_user = {}
    coins_by_user = {}
    modules_by_user = {}
    if user_ids:
        from app.achievements.models import StreakCoins, UserStatistics
        from app.modules.models import UserModule

        stats_by_user = {
            s.user_id: s for s in UserStatistics.query.filter(UserStatistics.user_id.in_(user_ids)).all()
        }
        coins_by_user = {
            c.user_id: c for c in StreakCoins.query.filter(StreakCoins.user_id.in_(user_ids)).all()
        }
        module_rows = db.session.query(UserModule.user_id, func.count(UserModule.id)).filter(
            UserModule.user_id.in_(user_ids),
            UserModule.is_enabled.is_(True),
        ).group_by(UserModule.user_id).all()
        modules_by_user = {uid: count for uid, count in module_rows}

    user_rows = []
    for user in users_page:
        stats = stats_by_user.get(user.id)
        coins = coins_by_user.get(user.id)
        user_rows.append({
            'user': user,
            'stats': stats,
            'coins': coins,
            'modules_enabled': modules_by_user.get(user.id, 0),
        })

    active_count = User.query.filter(User.active.is_(True)).count()
    admin_count = User.query.filter(User.is_admin.is_(True)).count()
    inactive_7_cutoff = now - timedelta(days=7)
    inactive_7_count = User.query.filter(
        db.or_(User.last_login.is_(None), User.last_login < inactive_7_cutoff)
    ).count()
    email_ready_count = User.query.filter(
        User.email.isnot(None),
        User.email_opted_out.is_(False),
        User.notify_email_reminders.is_(True),
    ).count()

    return render_template(
        'admin/users.html',
        users=users_page,
        user_rows=user_rows,
        pagination=pagination,
        search=search,
        status=status,
        role=role,
        email_state=email_state,
        activity=activity,
        sort=sort,
        per_page=per_page,
        now=now,
        summary={
            'total': User.query.count(),
            'active': active_count,
            'admins': admin_count,
            'inactive_7': inactive_7_count,
            'email_ready': email_ready_count,
        },
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


@user_bp.route('/users/bulk', methods=['POST'])
@admin_required
def bulk_users():
    """Apply safe bulk actions from the users console."""
    action = (request.form.get('bulk_action') or '').strip()
    raw_ids = request.form.getlist('user_ids')
    try:
        user_ids = sorted({int(uid) for uid in raw_ids})
    except (TypeError, ValueError):
        flash('Некорректный список пользователей.', 'danger')
        return redirect(url_for('user_admin.users'))

    if not user_ids:
        flash('Выберите хотя бы одного пользователя.', 'warning')
        return redirect(url_for('user_admin.users'))

    users_to_update = User.query.filter(User.id.in_(user_ids)).all()
    changed = 0

    if action in {'activate', 'deactivate'}:
        target_active = action == 'activate'
        for user in users_to_update:
            if user.id == current_user.id and not target_active:
                continue
            if user.active != target_active:
                user.active = target_active
                changed += 1
        log_admin_action(
            current_user.id,
            'user.bulk_activate' if target_active else 'user.bulk_deactivate',
            target_type='user',
        )
        db.session.commit()
        flash(f'Обновлено пользователей: {changed}.', 'success')
    else:
        flash('Неизвестное массовое действие.', 'danger')

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


@user_bp.route('/users/<int:user_id>/identity', methods=['POST'])
@admin_required
def update_user_identity(user_id):
    """Update username/email from the admin user profile."""
    user = User.query.get_or_404(user_id)
    username = (request.form.get('username') or '').strip()[:64]
    email = (request.form.get('email') or '').strip()[:120] or None

    if not username:
        flash('Username не может быть пустым.', 'danger')
        return redirect(url_for('user_admin.user_detail', user_id=user_id))

    existing_username = User.query.filter(User.username == username, User.id != user.id).first()
    if existing_username:
        flash('Такой username уже занят.', 'danger')
        return redirect(url_for('user_admin.user_detail', user_id=user_id))

    if email:
        existing_email = User.query.filter(User.email == email, User.id != user.id).first()
        if existing_email:
            flash('Такой email уже занят.', 'danger')
            return redirect(url_for('user_admin.user_detail', user_id=user_id))

    user.username = username
    user.email = email
    log_admin_action(current_user.id, 'user.update_identity', target_type='user', target_id=user.id)
    db.session.commit()
    flash('Профиль пользователя обновлен.', 'success')
    return redirect(url_for('user_admin.user_detail', user_id=user_id))


@user_bp.route('/users/<int:user_id>/settings', methods=['POST'])
@admin_required
def update_user_settings(user_id):
    """Update learning, onboarding, notification and plan settings."""
    user = User.query.get_or_404(user_id)

    def _int_field(name: str, default: int, min_value: int, max_value: int) -> int:
        try:
            value = int(request.form.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(min_value, min(value, max_value))

    onboarding_level = (request.form.get('onboarding_level') or '').strip().upper()
    if onboarding_level not in VALID_ONBOARDING_LEVELS:
        onboarding_level = user.onboarding_level or ''

    plan_difficulty = (request.form.get('plan_difficulty') or 'normal').strip()
    if plan_difficulty not in VALID_PLAN_DIFFICULTIES:
        plan_difficulty = 'normal'

    pause_raw = (request.form.get('plan_paused_until') or '').strip()
    paused_until = None
    if pause_raw:
        try:
            paused_until = date.fromisoformat(pause_raw)
        except ValueError:
            flash('Дата паузы плана некорректна.', 'danger')
            return redirect(url_for('user_admin.user_detail', user_id=user_id))

    user.onboarding_completed = 'onboarding_completed' in request.form
    user.onboarding_level = onboarding_level or None
    user.onboarding_focus = (request.form.get('onboarding_focus') or '').strip()[:100] or None
    user.timezone = (request.form.get('timezone') or '').strip()[:50] or user.timezone
    user.daily_goal_minutes = _int_field('daily_goal_minutes', user.daily_goal_minutes or 15, 1, 240)
    user.listening_goal_minutes = _int_field('listening_goal_minutes', user.listening_goal_minutes or 10, 1, 240)
    user.daily_word_goal = _int_field('daily_word_goal', user.daily_word_goal or 10, 1, 200)
    user.weekly_lesson_goal = _int_field('weekly_lesson_goal', user.weekly_lesson_goal or 5, 1, 100)
    user.plan_difficulty = plan_difficulty
    user.plan_paused_until = paused_until
    user.email_opted_out = 'email_opted_out' in request.form
    user.notify_email_reminders = 'notify_email_reminders' in request.form
    user.notify_in_app_achievements = 'notify_in_app_achievements' in request.form
    user.notify_in_app_streaks = 'notify_in_app_streaks' in request.form
    user.notify_in_app_weekly = 'notify_in_app_weekly' in request.form
    user.streak_shield_active = 'streak_shield_active' in request.form

    log_admin_action(current_user.id, 'user.update_settings', target_type='user', target_id=user.id)
    db.session.commit()
    flash('Настройки пользователя сохранены.', 'success')
    return redirect(url_for('user_admin.user_detail', user_id=user_id))


@user_bp.route('/users/<int:user_id>/send-password-reset', methods=['POST'])
@admin_required
def send_password_reset(user_id):
    """Send a password reset email to a user from admin console."""
    user = User.query.get_or_404(user_id)
    if not user.email:
        flash('У пользователя нет email.', 'danger')
        return redirect(url_for('user_admin.user_detail', user_id=user_id))

    from app.auth.routes import get_reset_token
    from app.utils.email_utils import email_sender

    token = get_reset_token(user.id)
    reset_url = url_for('auth.reset_password', token=token, _external=True)
    sent = email_sender.send_email(
        subject='Сброс пароля',
        to_email=user.email,
        template_name='password_reset',
        context={'username': user.username, 'reset_url': reset_url},
    )
    if sent:
        log_admin_action(current_user.id, 'user.send_password_reset', target_type='user', target_id=user.id)
        db.session.commit()
        flash('Письмо для сброса пароля отправлено.', 'success')
    else:
        flash('Не удалось отправить письмо. Проверь SMTP-настройки.', 'danger')
    return redirect(url_for('user_admin.user_detail', user_id=user_id))


@user_bp.route('/users/export')
@user_bp.route('/users/export.csv')
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
