# app/admin/utils/decorators.py

"""Decorators for the admin panel.

Two gates are exposed here:

* :func:`admin_required` — single source of truth for "must be authenticated as
  an admin" used by every admin blueprint. Anonymous users are bounced to the
  login page; authenticated non-admins also get bounced (so the admin URL
  surface is opaque to regular users). State-changing requests are mirrored to
  the ``audit.admin`` logger.

* :func:`admin_audit_required` — wraps :func:`admin_required` and additionally
  writes an :class:`AdminAuditLog` row via
  :func:`app.admin.audit.log_admin_action` once the wrapped view returns a
  successful response. Use it on destructive mutations so audit coverage cannot
  drift away from the route definition.

Both decorators preserve ``__wrapped__`` so the URL-inventory test in
``tests/admin/test_admin_url_inventory.py`` can introspect the chain.
"""

import logging
from functools import wraps
from typing import Any, Callable, Optional

from flask import flash, jsonify, make_response, redirect, request, url_for
from flask_login import current_user, login_required

from app.utils.db import db

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit.admin')


def _is_admin_user() -> bool:
    return bool(getattr(current_user, 'is_authenticated', False) and getattr(current_user, 'is_admin', False))


def admin_required(view_func: Callable[..., Any]) -> Callable[..., Any]:
    """Require an authenticated admin user. The single auth gate for admin routes."""

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not _is_admin_user():
            if getattr(current_user, 'is_authenticated', False):
                audit_logger.warning(
                    'Unauthorized admin access attempt: user_id=%s, username=%s, path=%s, ip=%s',
                    current_user.id, current_user.username, request.path, request.remote_addr,
                )
            flash('У вас нет прав для доступа к этой странице.', 'danger')
            return redirect(url_for('auth.login'))

        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            audit_logger.info(
                'Admin action: %s %s by user_id=%s (%s), ip=%s',
                request.method, request.path, current_user.id,
                current_user.username, request.remote_addr,
            )
        return view_func(*args, **kwargs)

    return login_required(wrapped_view)


def admin_audit_required(
    action: str,
    target_type: Optional[str] = None,
    target_id_arg: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Combine :func:`admin_required` with an :class:`AdminAuditLog` write.

    Args:
        action: ``entity.action`` snake_case identifier persisted in
            ``admin_audit_log.action`` (e.g. ``user.delete``).
        target_type: Optional target-type label, also persisted as-is.
        target_id_arg: Optional name of the view-function keyword argument
            (typically a path parameter such as ``user_id``) whose value should
            be persisted as ``admin_audit_log.target_id``.

    The audit row is staged only when the wrapped view returns a successful
    response (2xx / 3xx). Errors and 4xx responses are not audited because they
    mean no mutation took place.
    """

    def decorator(view_func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view_func)
        def wrapped_view(*args, **kwargs):
            response = view_func(*args, **kwargs)
            try:
                resp = make_response(response)
                if 200 <= resp.status_code < 400:
                    from app.admin.audit import log_admin_action  # local import to avoid cycle
                    target_id = None
                    if target_id_arg is not None:
                        raw = kwargs.get(target_id_arg)
                        if raw is not None:
                            try:
                                target_id = int(raw)
                            except (TypeError, ValueError):
                                target_id = None
                    admin_id = getattr(current_user, 'id', None)
                    if admin_id is not None:
                        log_admin_action(
                            admin_id=admin_id,
                            action=action,
                            target_type=target_type,
                            target_id=target_id,
                        )
                return resp
            except Exception:
                logger.exception('admin_audit_required failed to stage log for action=%s', action)
                return response

        return admin_required(wrapped_view)

    return decorator


def handle_admin_errors(return_json: bool = True):
    """Decorator for handling errors in admin operations."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)

                try:
                    db.session.rollback()
                except Exception:
                    logger.exception("Failed to rollback DB session in %s", func.__name__)

                if return_json:
                    return jsonify({
                        'success': False,
                        'error': 'Внутренняя ошибка сервера',
                        'operation': func.__name__,
                    }), 500
                flash('Произошла внутренняя ошибка. Попробуйте позже.', 'danger')
                return redirect(url_for('dashboard_admin.dashboard'))

        return wrapper

    return decorator


def cache_result(key: str, timeout: int = 300):
    """Decorator for caching function results.

    Args:
        key: Cache-key prefix.
        timeout: TTL in seconds (default 5 minutes).
    """
    from app.admin.utils.cache import get_cache, set_cache

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = f"{key}_{hash(str(args) + str(kwargs))}"

            cached_data = get_cache(cache_key, timeout)
            if cached_data is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_data

            result = func(*args, **kwargs)
            set_cache(cache_key, result)
            logger.debug(f"Cache miss for {cache_key}, result cached")
            return result

        return wrapper

    return decorator
