from functools import wraps
from flask import abort, redirect, url_for, flash, request
from flask_login import current_user

from app.modules.service import ModuleService


def module_required(module_code: str):
    """
    Декоратор для проверки доступа к модулю.

    Использование:
        @module_required('curriculum')
        def my_route():
            ...

    Args:
        module_code: Код модуля (например, 'curriculum', 'books', 'words')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Проверяем, авторизован ли пользователь
            if not current_user.is_authenticated:
                flash('Пожалуйста, войдите в систему для доступа к этому разделу.', 'warning')
                return redirect(url_for('auth.login', next=request.url))

            # Проверяем, доступен ли модуль для пользователя
            if not ModuleService.is_module_enabled_for_user(current_user.id, module_code):
                flash(f'У вас нет доступа к этому разделу. Обратитесь к администратору.', 'error')
                abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def admin_or_module_owner(module_code: str = None):
    """
    Декоратор для проверки, является ли пользователь админом или владельцем модуля.

    Использование:
        @admin_or_module_owner('curriculum')
        def edit_module():
            ...

    Args:
        module_code: Код модуля (опционально)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Пожалуйста, войдите в систему.', 'warning')
                return redirect(url_for('auth.login', next=request.url))

            # Админ имеет доступ ко всему
            if current_user.is_admin:
                return f(*args, **kwargs)

            # Если указан модуль, проверяем доступ к нему
            if module_code:
                if not ModuleService.is_module_enabled_for_user(current_user.id, module_code):
                    flash('У вас нет доступа к этому разделу.', 'error')
                    abort(403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator
