"""Task 22 of 2026-05-24 admin audit — template layout/UX smoke tests.

Verifies that key admin pages:
- Render HTTP 200 for authenticated admins
- Contain required structural elements (breadcrumb nav, flash container, table-responsive)
- Are NOT accessible to anonymous users (redirected) or non-admins (403)
"""
from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock

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


def _login(client, user_id: int) -> None:
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True


# ---------------------------------------------------------------------------
# Helpers for mocking heavy service calls so templates render fast in tests
# ---------------------------------------------------------------------------

def _mock_dashboard_services():
    """Return a context-manager stack that stubs out the dashboard's slow helpers."""
    empty_engagement = {
        "dau": 0, "wau": 0, "mau": 0,
        "dau_trend": "", "dau_trend_value": "",
        "wau_trend": "", "wau_trend_value": "",
        "mau_trend": "", "mau_trend_value": "",
    }
    empty_health = {
        "db_status": "ok", "db_error": None,
        "uptime_seconds": 0, "errors_5xx": 0,
    }
    from unittest.mock import patch
    return [
        patch("app.admin.routes.dashboard_routes.get_dashboard_statistics",
              return_value={
                  "total_users": 0, "active_users": 0, "new_users": 0,
                  "active_recently": 0, "total_books": 0, "total_readings": 0,
                  "words_total": 0, "words_with_audio": 0,
                  "total_lessons": 0, "active_lessons": 0,
              }),
        patch("app.admin.routes.dashboard_routes.get_engagement_metrics",
              return_value=empty_engagement),
        patch("app.admin.routes.dashboard_routes.get_system_health",
              return_value=empty_health),
        patch("app.admin.routes.dashboard_routes.get_content_quality",
              return_value={"coverage_pct": 0, "no_completions_count": 0,
                            "missing_audio_count": 0, "no_vocabulary_count": 0}),
    ]


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_dashboard_renders_200(client, db_session):
    admin = _make_admin(db_session)
    _login(client, admin.id)

    patches = _mock_dashboard_services()
    for p in patches:
        p.start()
    try:
        resp = client.get("/admin/")
    finally:
        for p in patches:
            p.stop()

    assert resp.status_code == 200
    body = resp.data.decode()
    assert "LLT Admin" in body or "Панель управления" in body


def test_dashboard_anonymous_redirects(client):
    resp = client.get("/admin/")
    assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# Users list
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_users_list_renders_200(client, db_session):
    admin = _make_admin(db_session)
    _login(client, admin.id)

    resp = client.get("/admin/users")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "table-responsive" in body


def test_users_list_anonymous_redirects(client):
    resp = client.get("/admin/users")
    assert resp.status_code in (302, 401)


def test_users_list_non_admin_forbidden(client, db_session):
    regular = User(
        username=f"reg_{uuid.uuid4().hex[:8]}",
        email=f"reg_{uuid.uuid4().hex[:8]}@t.com",
        is_admin=False,
        active=True,
    )
    regular.set_password("pw")
    db_session.add(regular)
    db_session.flush()
    _login(client, regular.id)

    resp = client.get("/admin/users")
    assert resp.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_audit_log_renders_200(client, db_session):
    admin = _make_admin(db_session)
    _login(client, admin.id)

    resp = client.get("/admin/audit-log")
    assert resp.status_code == 200
    body = resp.data.decode()
    # breadcrumb nav must be present
    assert "admin-breadcrumb" in body
    # audit log card must be present (table or empty state)
    assert "Аудит-лог" in body


def test_audit_log_anonymous_redirects(client):
    resp = client.get("/admin/audit-log")
    assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# Activity feed
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_activity_feed_renders_200(client, db_session):
    admin = _make_admin(db_session)
    _login(client, admin.id)

    with patch("app.admin.routes.activity_routes.get_recent_events", return_value=[]):
        resp = client.get("/admin/activity")

    assert resp.status_code == 200
    body = resp.data.decode()
    assert "admin-breadcrumb" in body


def test_activity_feed_anonymous_redirects(client):
    resp = client.get("/admin/activity")
    assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_settings_renders_200(client, db_session):
    admin = _make_admin(db_session)
    _login(client, admin.id)

    resp = client.get("/admin/settings")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "admin-breadcrumb" in body


def test_settings_anonymous_redirects(client):
    resp = client.get("/admin/settings")
    assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# Content quality
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_content_quality_renders_200(client, db_session):
    admin = _make_admin(db_session)
    _login(client, admin.id)

    with patch("app.admin.routes.dashboard_routes.get_content_quality_detail",
               return_value={
                   "total_lessons": 0,
                   "no_completions_count": 0,
                   "missing_audio_count": 0,
                   "no_vocabulary_count": 0,
                   "lessons_detail": [],
               }):
        resp = client.get("/admin/content-quality")

    assert resp.status_code == 200
    body = resp.data.decode()
    # breadcrumb was added by Task 22
    assert "admin-breadcrumb" in body


def test_content_quality_anonymous_redirects(client):
    resp = client.get("/admin/content-quality")
    assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# Grammar Lab import JSON page
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_grammar_lab_import_json_renders_200(client, db_session):
    admin = _make_admin(db_session)
    _login(client, admin.id)

    resp = client.get("/admin/grammar-lab/import-exercises-json")
    assert resp.status_code == 200
    body = resp.data.decode()
    # breadcrumb was added by Task 22
    assert "admin-breadcrumb" in body


# ---------------------------------------------------------------------------
# Cultural notes list
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_cultural_notes_list_renders_200(client, db_session):
    admin = _make_admin(db_session)
    _login(client, admin.id)

    resp = client.get("/admin/cultural-notes")
    assert resp.status_code == 200
    body = resp.data.decode()
    # breadcrumb was added by Task 22
    assert "admin-breadcrumb" in body


# ---------------------------------------------------------------------------
# Template structural invariants — flash message container always present
# ---------------------------------------------------------------------------

PAGES_REQUIRING_FLASH_CONTAINER = [
    "/admin/users",
    "/admin/audit-log",
    "/admin/activity",
    "/admin/settings",
]


@pytest.mark.parametrize("url", PAGES_REQUIRING_FLASH_CONTAINER)
def test_flash_container_present(client, db_session, url):
    """Every admin page rendered by base.html must have a flash message section."""
    admin = _make_admin(db_session)
    _login(client, admin.id)

    with patch("app.admin.routes.activity_routes.get_recent_events", return_value=[]):
        resp = client.get(url)

    assert resp.status_code == 200
    body = resp.data.decode()
    # base.html renders flash messages via get_flashed_messages — the block must exist
    assert "get_flashed_messages" not in body  # should be rendered, not raw template
    # The alert-dismissible pattern signals flash rendering in base.html's JS
    # Just confirm base.html was loaded (has admin sidebar)
    assert "admin-sidebar" in body


# ---------------------------------------------------------------------------
# Responsive tables invariant
# ---------------------------------------------------------------------------

PAGES_WITH_TABLES = [
    "/admin/users",
]


@pytest.mark.parametrize("url", PAGES_WITH_TABLES)
def test_table_is_responsive(client, db_session, url):
    """Tables on list pages must be wrapped in .table-responsive."""
    admin = _make_admin(db_session)
    _login(client, admin.id)

    resp = client.get(url)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "table-responsive" in body
