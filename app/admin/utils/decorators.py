# app/admin/utils/decorators.py

"""
Декораторы для административной панели LLT English
"""
import logging
from functools import wraps
from datetime import datetime, timezone

from flask import flash, redirect, url_for, jsonify
from flask_login import current_user, login_required

from app.utils.db import db

logger = logging.getLogger(__name__)


def admin_required(view_func):
    """Декоратор для проверки прав администратора"""

    def wrapped_view(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('У вас нет прав для доступа к этой странице.', 'danger')
            return redirect(url_for('auth.login'))
        return view_func(*args, **kwargs)

    wrapped_view.__name__ = view_func.__name__
    return login_required(wrapped_view)


def handle_admin_errors(return_json=True):
    """Декоратор для обработки ошибок в админ операциях"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)

                # Откатываем изменения в базе данных
                try:
                    db.session.rollback()
                except:
                    pass

                if return_json:
                    return jsonify({
                        'success': False,
                        'error': f'Внутренняя ошибка сервера: {str(e)}',
                        'operation': func.__name__
                    }), 500
                else:
                    flash(f'Ошибка в операции {func.__name__}: {str(e)}', 'danger')
                    return redirect(url_for('admin.dashboard'))

        return wrapper

    return decorator


def cache_result(key, timeout=300):
    """
    Декоратор для кэширования результатов функций

    Args:
        key: Ключ для кэша
        timeout: Время жизни кэша в секундах (по умолчанию 5 минут)
    """
    from app.admin.utils.cache import get_cache, set_cache

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{key}_{hash(str(args) + str(kwargs))}"

            # Проверяем кэш
            cached_data = get_cache(cache_key, timeout)
            if cached_data is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_data

            # Выполняем функцию и кэшируем результат
            result = func(*args, **kwargs)
            set_cache(cache_key, result)
            logger.debug(f"Cache miss for {cache_key}, result cached")

            return result

        return wrapper

    return decorator
