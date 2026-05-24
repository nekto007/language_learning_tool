# app/admin/routes/system_routes.py

"""
System Management Routes для административной панели
Маршруты для управления системой и базой данных
"""
import logging

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin.audit import log_admin_action
from app.admin.services.system_service import SystemService
from app.admin.utils.decorators import admin_required
from app.admin.utils.cache import clear_admin_cache, clear_cache_by_prefix, get_cache_stats
from app.curriculum.rate_limiter import rate_limit
from app.utils.db import db

# Создаем blueprint для system routes
system_bp = Blueprint('system_admin', __name__)

logger = logging.getLogger(__name__)

# Confirmation tokens required from the operator to prove intent for
# destructive system operations. The strings are surfaced verbatim in the UI
# so the admin must transcribe them — protects against accidental form
# resubmission and CSRF token leaks that would otherwise let one click
# trigger an irreversible action.
CLEAR_CACHE_CONFIRM = 'CLEAR_CACHE'
INIT_DATABASE_CONFIRM = 'INIT_DATABASE'


def _confirmation_ok(field: str, expected: str) -> bool:
    return (request.form.get(field) or '').strip() == expected


@system_bp.route('/system/clear-cache', methods=['POST'])
@admin_required
@rate_limit(limit=10, window=60, per='user')
def clear_cache():
    """Очистка административного кэша. Требует confirm=CLEAR_CACHE."""
    if not _confirmation_ok('confirm', CLEAR_CACHE_CONFIRM):
        logger.warning(
            'clear_cache rejected: missing/invalid confirmation by admin_id=%s',
            current_user.id,
        )
        flash('Подтверждение не получено — операция отменена.', 'warning')
        return redirect(url_for('system_admin.system'))

    try:
        clear_admin_cache()
        log_admin_action(current_user.id, 'system.clear_cache')
        db.session.commit()
        flash('Кэш успешно очищен', 'success')
        logger.info("Cache cleared by admin user %s", current_user.username)
    except Exception as e:
        logger.error("Error clearing cache: %s", e)
        flash(f'Ошибка при очистке кэша: {e}', 'danger')

    return redirect(url_for('system_admin.system'))


@system_bp.route('/system/cache-stats')
@admin_required
def cache_stats():
    """JSON snapshot of the current worker's in-memory cache."""
    return jsonify(get_cache_stats())


@system_bp.route('/system/clear-cache-prefix', methods=['POST'])
@admin_required
@rate_limit(limit=20, window=60, per='user')
def clear_cache_prefix():
    """Clear cache entries matching a given prefix."""
    prefix = (request.form.get('prefix') or '').strip()
    if not prefix:
        flash('Префикс не указан — операция отменена.', 'warning')
        return redirect(url_for('system_admin.system'))

    removed = clear_cache_by_prefix(prefix)
    log_admin_action(current_user.id, 'system.clear_cache_prefix', target_type=prefix[:64])
    db.session.commit()
    flash(f'Удалено {removed} записей кэша с префиксом «{prefix}»', 'success')
    logger.info(
        "Cache prefix '%s' cleared by admin_id=%s (%d entries)",
        prefix, current_user.id, removed,
    )
    return redirect(url_for('system_admin.system'))


@system_bp.route('/system')
@admin_required
def system():
    """Информация о системе"""
    info = SystemService.get_system_info()

    if 'error' in info:
        flash(f'Ошибка при получении системной информации: {info["error"]}', 'danger')
        return redirect(url_for('dashboard_admin.dashboard'))

    return render_template(
        'admin/system.html',
        system_info=info['system_info'],
        db_stats=info['db_stats'],
        app_info=info['app_info'],
        clear_cache_confirm=CLEAR_CACHE_CONFIRM,
        cache_stats=get_cache_stats(),
    )


@system_bp.route('/system/database')
@admin_required
def database_management():
    """Управление базой данных"""
    try:
        db_connection_status = SystemService.test_database_connection()
        word_stats = SystemService.get_word_status_statistics()
        book_stats = SystemService.get_book_statistics()
        recent_operations = SystemService.get_recent_db_operations()
    except Exception as e:
        logger.error("Error getting database info: %s", e)
        flash(f'Ошибка при получении информации о БД: {e}', 'danger')
        db_connection_status = {'status': 'error', 'message': str(e)}
        word_stats = {}
        book_stats = {}
        recent_operations = []

    return render_template(
        'admin/database.html',
        db_connection_status=db_connection_status,
        word_stats=word_stats,
        book_stats=book_stats,
        recent_operations=recent_operations,
        init_db_confirm=INIT_DATABASE_CONFIRM,
    )


@system_bp.route('/system/database/init', methods=['POST'])
@admin_required
@rate_limit(limit=3, window=300, per='user')
def init_database():
    """Инициализация базы данных. Требует confirm=INIT_DATABASE."""
    if not _confirmation_ok('confirm', INIT_DATABASE_CONFIRM):
        logger.warning(
            'init_database rejected: missing/invalid confirmation by admin_id=%s',
            current_user.id,
        )
        flash(
            f'Введите «{INIT_DATABASE_CONFIRM}» в поле подтверждения — операция отменена.',
            'warning',
        )
        return redirect(url_for('system_admin.database_management'))

    try:
        from app.utils.db_init import init_db
        init_db(current_app)
        log_admin_action(current_user.id, 'system.init_database')
        db.session.commit()
        flash('База данных успешно инициализирована!', 'success')
        logger.info("Database initialized by admin user %s", current_user.username)
    except Exception as e:
        logger.error("Error initializing database: %s", e)
        flash(f'Ошибка при инициализации БД: {e}', 'danger')

    return redirect(url_for('system_admin.database_management'))


@system_bp.route('/system/database/test-connection')
@admin_required
@rate_limit(limit=30, window=60, per='user')
def test_db_connection():
    """Тест подключения к базе данных"""
    try:
        result = SystemService.test_database_connection()
        return jsonify(result)
    except Exception as e:
        logger.error("Database connection test failed: %s", e)
        return jsonify({
            'status': 'error',
            'message': f'Ошибка подключения: {e}'
        }), 500
