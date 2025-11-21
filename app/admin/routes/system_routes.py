# app/admin/routes/system_routes.py

"""
System Management Routes для административной панели
Маршруты для управления системой и базой данных
"""
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, url_for
from flask_login import current_user

from app.admin.services.system_service import SystemService
from app.admin.utils.decorators import admin_required
from app.admin.utils.cache import clear_admin_cache

# Создаем blueprint для system routes
system_bp = Blueprint('system_admin', __name__)

logger = logging.getLogger(__name__)


@system_bp.route('/system/clear-cache', methods=['POST'])
@admin_required
def clear_cache():
    """Очистка административного кэша"""
    try:
        clear_admin_cache()
        flash('Кэш успешно очищен', 'success')
        logger.info(f"Cache cleared by admin user {current_user.username}")
    except Exception as e:
        logger.error(f"Error clearing cache: {str(e)}")
        flash(f'Ошибка при очистке кэша: {str(e)}', 'danger')

    return redirect(url_for('system_admin.system'))


@system_bp.route('/system')
@admin_required
def system():
    """Информация о системе"""
    info = SystemService.get_system_info()

    if 'error' in info:
        flash(f'Ошибка при получении системной информации: {info["error"]}', 'danger')
        return redirect(url_for('admin.dashboard'))

    return render_template(
        'admin/system.html',
        system_info=info['system_info'],
        db_stats=info['db_stats'],
        app_info=info['app_info']
    )


@system_bp.route('/system/database')
@admin_required
def database_management():
    """Управление базой данных"""
    try:
        # Проверка подключения к БД
        db_connection_status = SystemService.test_database_connection()

        # Статистика по пользовательским словам
        word_stats = SystemService.get_word_status_statistics()

        # Статистика по книгам
        book_stats = SystemService.get_book_statistics()

        # Недавние операции с БД
        recent_operations = SystemService.get_recent_db_operations()

    except Exception as e:
        logger.error(f"Error getting database info: {str(e)}")
        flash(f'Ошибка при получении информации о БД: {str(e)}', 'danger')
        db_connection_status = {'status': 'error', 'message': str(e)}
        word_stats = {}
        book_stats = {}
        recent_operations = []

    return render_template(
        'admin/database.html',
        db_connection_status=db_connection_status,
        word_stats=word_stats,
        book_stats=book_stats,
        recent_operations=recent_operations
    )


@system_bp.route('/system/database/init', methods=['POST'])
@admin_required
def init_database():
    """Инициализация базы данных"""
    try:
        from app.utils.db_init import init_db
        init_db()
        flash('База данных успешно инициализирована!', 'success')
        logger.info(f"Database initialized by admin user {current_user.username}")
    except Exception as e:
        logger.error(f"Error initializing database: {str(e)}")
        flash(f'Ошибка при инициализации БД: {str(e)}', 'danger')

    return redirect(url_for('system_admin.database_management'))


@system_bp.route('/system/database/test-connection')
@admin_required
def test_db_connection():
    """Тест подключения к базе данных"""
    try:
        result = SystemService.test_database_connection()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Database connection test failed: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f'Ошибка подключения: {str(e)}'
        }), 500
