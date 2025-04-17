"""
Основной модуль административной панели для LLT English
"""
import logging
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import desc, func

from app.auth.models import User
from app.utils.db import db

admin = Blueprint('admin', __name__, url_prefix='/admin')

# Настройка логирования
logger = logging.getLogger(__name__)


# Декоратор для проверки прав администратора
def admin_required(view_func):
    """Декоратор для проверки прав администратора"""

    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('У вас нет прав для доступа к этой странице.', 'danger')
            return redirect(url_for('auth.login'))
        return view_func(*args, **kwargs)

    wrapped_view.__name__ = view_func.__name__
    return login_required(wrapped_view)


@admin.route('/')
@admin_required
def dashboard():
    """Главная страница административной панели"""
    # Основная статистика для панели управления
    total_users = User.query.count()
    active_users = User.query.filter_by(active=True).count()

    # Пользователи, зарегистрировавшиеся за последние 7 дней
    week_ago = datetime.utcnow() - timedelta(days=7)
    new_users = User.query.filter(User.created_at >= week_ago).count()

    # Активные пользователи за последние 7 дней
    active_recently = User.query.filter(User.last_login >= week_ago).count()

    # Последние зарегистрированные пользователи
    recent_users = User.query.order_by(desc(User.created_at)).limit(10).all()

    # Статистика по книгам
    try:
        from app.books.models import Book
        total_books = db.session.query(func.count(Book.id)).scalar() or 0
        total_readings = db.session.query(func.sum(Book.unique_words)).scalar() or 0
    except:
        total_books = 0
        total_readings = 0

    # Статистика по словам
    try:
        from app.words.models import CollectionWords
        total_words = db.session.query(func.count(CollectionWords.id)).scalar() or 0
    except:
        total_words = 0

    return render_template(
        'admin/dashboard.html',
        total_users=total_users,
        active_users=active_users,
        new_users=new_users,
        active_recently=active_recently,
        recent_users=recent_users,
        total_books=total_books,
        total_readings=total_readings,
        total_words=total_words
    )


@admin.route('/users')
@admin_required
def users():
    """Управление пользователями"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '')

    # Построение запроса с учетом поиска
    query = User.query

    if search:
        query = query.filter(
            (User.username.ilike(f'%{search}%')) |
            (User.email.ilike(f'%{search}%'))
        )

    # Пагинация
    pagination = query.order_by(desc(User.last_login)).paginate(
        page=page, per_page=per_page, error_out=False
    )

    users = pagination.items

    now = datetime.utcnow()

    return render_template(
        'admin/users.html',
        users=users,
        pagination=pagination,
        search=search,
        now=now
    )


@admin.route('/users/<int:user_id>/toggle_status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    """Активация/деактивация пользователя"""
    user = User.query.get_or_404(user_id)
    user.active = not user.active
    db.session.commit()

    status = "активирован" if user.active else "деактивирован"
    flash(f'Пользователь {user.username} успешно {status}.', 'success')

    return redirect(url_for('admin.users'))


@admin.route('/users/<int:user_id>/toggle_admin', methods=['POST'])
@admin_required
def toggle_admin_status(user_id):
    """Предоставление/отзыв прав администратора"""
    if current_user.id == user_id:
        flash('Вы не можете изменить свои собственные права администратора.', 'danger')
        return redirect(url_for('admin.users'))

    user = User.query.get_or_404(user_id)
    user.is_admin = not user.is_admin
    db.session.commit()

    status = "предоставлены" if user.is_admin else "отозваны"
    flash(f'Права администратора для пользователя {user.username} успешно {status}.', 'success')

    return redirect(url_for('admin.users'))


@admin.route('/stats')
@admin_required
def stats():
    """Статистика приложения"""
    # Данные по регистрациям пользователей по дням за последний месяц
    month_ago = datetime.utcnow() - timedelta(days=30)
    user_registrations = db.session.query(
        func.date(User.created_at).label('date'),
        func.count(User.id).label('count')
    ).filter(User.created_at >= month_ago).group_by(func.date(User.created_at)).all()

    # Для графика активности пользователей
    user_logins = db.session.query(
        func.date(User.last_login).label('date'),
        func.count(User.id).label('count')
    ).filter(User.last_login >= month_ago).group_by(func.date(User.last_login)).all()

    # Активность по часам суток
    user_activity_by_hour = db.session.query(
        func.extract('hour', User.last_login).label('hour'),
        func.count(User.id).label('count')
    ).filter(User.last_login >= month_ago).group_by('hour').all()

    return render_template(
        'admin/stats.html',
        user_registrations=user_registrations,
        user_logins=user_logins,
        user_activity_by_hour=user_activity_by_hour
    )


@admin.route('/system')
@admin_required
def system():
    """Информация о системе"""
    import platform
    import psutil
    import os

    system_info = {
        'platform': platform.platform(),
        'python_version': platform.python_version(),
        'cpu_count': psutil.cpu_count(),
        'memory': {
            'total': psutil.virtual_memory().total // (1024 * 1024),  # МБ
            'available': psutil.virtual_memory().available // (1024 * 1024),  # МБ
            'used_percent': psutil.virtual_memory().percent
        },
        'disk': {
            'total': psutil.disk_usage('/').total // (1024 * 1024 * 1024),  # ГБ
            'used': psutil.disk_usage('/').used // (1024 * 1024 * 1024),  # ГБ
            'free': psutil.disk_usage('/').free // (1024 * 1024 * 1024),  # ГБ
            'used_percent': psutil.disk_usage('/').percent
        }
    }

    # Информация о Flask-приложении
    app_info = {
        'debug': current_app.debug,
        'testing': current_app.testing,
        'secret_key_set': bool(current_app.secret_key),
        'static_folder': current_app.static_folder,
        'template_folder': current_app.template_folder,
        'instance_path': current_app.instance_path,
        'blueprints': list(current_app.blueprints.keys())
    }

    # Переменные окружения (безопасные)
    safe_env_vars = {
        'FLASK_ENV': os.environ.get('FLASK_ENV', 'Not set'),
        'FLASK_APP': os.environ.get('FLASK_APP', 'Not set'),
        'FLASK_DEBUG': os.environ.get('FLASK_DEBUG', 'Not set'),
        'DATABASE_URL': 'Hidden for security' if os.environ.get('DATABASE_URL') else 'Not set',
        'SERVER_NAME': os.environ.get('SERVER_NAME', 'Not set')
    }

    return render_template(
        'admin/system.html',
        system_info=system_info,
        app_info=app_info,
        safe_env_vars=safe_env_vars
    )
