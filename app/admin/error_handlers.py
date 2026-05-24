# app/admin/error_handlers.py
"""Admin-specific HTTP error page rendering.

Called from the app-level error handlers in app/__init__.py when the failing
request is under the /admin/ prefix, so admins see branded error pages with
a "back to hub" link instead of the generic public error pages.
"""
from __future__ import annotations

from flask import render_template, request


def is_admin_request() -> bool:
    """Return True when the current request targets an /admin/* URL."""
    return request.path.startswith("/admin")


def render_admin_403() -> tuple[str, int]:
    return render_template("admin/errors/403.html"), 403


def render_admin_404() -> tuple[str, int]:
    return render_template("admin/errors/404.html"), 404


def render_admin_500() -> tuple[str, int]:
    return render_template("admin/errors/500.html"), 500
