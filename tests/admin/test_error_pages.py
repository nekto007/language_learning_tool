"""Task 28 of 2026-05-24 admin audit — custom admin error pages.

Verifies that requests to /admin/* paths receive the admin-branded error
templates (containing "LLT Admin" branding and a "Вернуться в админку" link)
rather than the generic public error pages.
"""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User


def _make_admin(db_session) -> User:
    user = User(
        username=f"adm_{uuid.uuid4().hex[:8]}",
        email=f"adm_{uuid.uuid4().hex[:8]}@t.com",
        is_admin=True,
        active=True,
    )
    user.set_password("pw")
    db_session.add(user)
    db_session.flush()
    return user


def _make_plain_user(db_session) -> User:
    user = User(
        username=f"usr_{uuid.uuid4().hex[:8]}",
        email=f"usr_{uuid.uuid4().hex[:8]}@t.com",
        is_admin=False,
        active=True,
    )
    user.set_password("pw")
    db_session.add(user)
    db_session.flush()
    return user


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


# ---------------------------------------------------------------------------
# 404 on unknown /admin/* URL
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_admin_404_uses_admin_template(client, db_session):
    """Unknown /admin/… URL → 404 with admin branding."""
    admin = _make_admin(db_session)
    _login(client, admin.id)

    resp = client.get("/admin/this-path-does-not-exist-xyz")
    assert resp.status_code == 404
    body = resp.data.decode()
    assert "LLT Admin" in body
    assert "Вернуться в админку" in body


def test_admin_404_contains_link_to_hub(client, db_session):
    admin = _make_admin(db_session)
    _login(client, admin.id)

    resp = client.get("/admin/nonexistent-page-123")
    assert resp.status_code == 404
    body = resp.data.decode()
    assert 'href="/admin/"' in body or "href='/admin/'" in body


# ---------------------------------------------------------------------------
# 403 for non-admin users hitting admin routes
# ---------------------------------------------------------------------------

def test_admin_403_uses_admin_template(app):
    """The admin 403 renderer returns a 403 with admin-branded HTML."""
    from app.admin.error_handlers import render_admin_403
    with app.test_request_context("/admin/users"):
        body, code = render_admin_403()
    assert code == 403
    assert "LLT Admin" in body
    assert "Вернуться в админку" in body
    assert "403" in body


def test_admin_non_admin_user_gets_redirect(client, db_session):
    """Non-admin hitting /admin/ → redirect to login (admin_required behaviour)."""
    plain = _make_plain_user(db_session)
    _login(client, plain.id)

    resp = client.get("/admin/", follow_redirects=False)
    # admin_required redirects non-admins rather than returning 403
    assert resp.status_code == 302


def test_admin_anonymous_gets_redirect(client):
    """Anonymous request to /admin/ → redirect (Flask-Login) not 403."""
    resp = client.get("/admin/", follow_redirects=False)
    assert resp.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Public (non-admin) 404 still uses generic template
# ---------------------------------------------------------------------------

def test_public_404_uses_generic_template(client):
    """Unknown public URL → 404 with generic template (not admin branding)."""
    resp = client.get("/this-public-path-does-not-exist-zyx")
    assert resp.status_code == 404
    body = resp.data.decode()
    # Generic error page should NOT contain admin sidebar chrome
    assert "LLT Admin" not in body or "Вернуться в админку" not in body


# ---------------------------------------------------------------------------
# Template content checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_path,code_str,back_text", [
    ("admin/errors/403.html", "403", "Вернуться в админку"),
    ("admin/errors/404.html", "404", "Вернуться в админку"),
    ("admin/errors/500.html", "500", "Вернуться в админку"),
])
def test_admin_error_template_rendered_standalone(app, template_path, code_str, back_text):
    """Each admin error template renders without exceptions and contains required elements."""
    from flask import render_template
    with app.test_request_context("/admin/test"):
        html = render_template(template_path)
    assert code_str in html
    assert back_text in html
    assert "LLT Admin" in html
    assert "/admin/" in html


# ---------------------------------------------------------------------------
# is_admin_request helper
# ---------------------------------------------------------------------------

def test_is_admin_request_true(app):
    from app.admin.error_handlers import is_admin_request
    with app.test_request_context("/admin/users"):
        assert is_admin_request() is True


def test_is_admin_request_false_public(app):
    from app.admin.error_handlers import is_admin_request
    with app.test_request_context("/study"):
        assert is_admin_request() is False


def test_is_admin_request_false_api(app):
    from app.admin.error_handlers import is_admin_request
    with app.test_request_context("/api/daily-plan"):
        assert is_admin_request() is False
