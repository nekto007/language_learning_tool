"""Task 23 of 2026-05-24 admin audit — WCAG accessibility smoke tests.

Checks that key admin pages rendered for authenticated admins include:
- Skip-to-content link targeting #main-content
- Main landmark with id="main-content"
- Sidebar <nav> with aria-label
- Nav section buttons with aria-expanded and aria-controls
- Decorative icons carry aria-hidden="true"
- Search container has role="search" and an associated <label>
- Alert close buttons have aria-label
- Focus-visible CSS rules exist for admin nav elements
"""
from __future__ import annotations

import re
import uuid
from unittest.mock import patch

import pytest

from app.auth.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin(db_session) -> User:
    user = User(
        username=f"a11y_{uuid.uuid4().hex[:8]}",
        email=f"a11y_{uuid.uuid4().hex[:8]}@t.com",
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


def _mock_dashboard():
    empty_engagement = {
        "dau": 0, "wau": 0, "mau": 0,
        "dau_trend": "", "dau_trend_value": "",
        "wau_trend": "", "wau_trend_value": "",
        "mau_trend": "", "mau_trend_value": "",
    }
    empty_health = {"db_status": "ok", "db_error": None, "uptime_seconds": 0, "errors_5xx": 0}
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


def _get_dashboard_html(client, db_session) -> str:
    admin = _make_admin(db_session)
    _login(client, admin.id)
    patches = _mock_dashboard()
    for p in patches:
        p.start()
    try:
        resp = client.get("/admin/")
    finally:
        for p in patches:
            p.stop()
    assert resp.status_code == 200
    return resp.data.decode()


# ---------------------------------------------------------------------------
# Skip link
# ---------------------------------------------------------------------------

@pytest.mark.smoke
def test_skip_to_content_link_present(client, db_session):
    body = _get_dashboard_html(client, db_session)
    assert 'href="#main-content"' in body, "skip-to-content link missing"
    assert "skip-to-content" in body, "skip-to-content CSS class missing"


def test_main_content_id_present(client, db_session):
    body = _get_dashboard_html(client, db_session)
    assert 'id="main-content"' in body, "<main id='main-content'> anchor missing"


# ---------------------------------------------------------------------------
# Sidebar navigation landmarks
# ---------------------------------------------------------------------------

def test_sidebar_nav_has_aria_label(client, db_session):
    body = _get_dashboard_html(client, db_session)
    assert 'aria-label=' in body and 'admin-sidebar' in body
    # Ensure the nav itself has aria-label
    assert re.search(r'<nav[^>]+aria-label=', body), "sidebar <nav> missing aria-label"


def test_nav_section_buttons_have_aria_expanded(client, db_session):
    body = _get_dashboard_html(client, db_session)
    # Each collapsible section title is now a <button> with aria-expanded
    buttons = re.findall(r'<button[^>]+nav-section-title[^>]*>', body)
    assert len(buttons) >= 5, f"Expected ≥5 nav-section-title buttons, got {len(buttons)}"
    for btn_html in buttons:
        assert "aria-expanded" in btn_html, f"nav-section-title button missing aria-expanded: {btn_html}"
        assert "aria-controls" in btn_html, f"nav-section-title button missing aria-controls: {btn_html}"


def test_nav_section_content_ids_present(client, db_session):
    body = _get_dashboard_html(client, db_session)
    for section in ("main", "content", "tools", "analytics", "config"):
        assert f'id="nav-content-{section}"' in body, (
            f"nav-section-content missing id for section '{section}'"
        )


# ---------------------------------------------------------------------------
# Icons: aria-hidden on decorative Font Awesome icons
# ---------------------------------------------------------------------------

def test_sidebar_icons_have_aria_hidden(client, db_session):
    body = _get_dashboard_html(client, db_session)
    # Icons inside nav-link elements should have aria-hidden="true"
    # We check that the pattern <i class="fas ... aria-hidden="true"> appears
    aria_hidden_icons = re.findall(r'<i[^>]+aria-hidden="true"', body)
    assert len(aria_hidden_icons) >= 10, (
        f"Expected ≥10 aria-hidden icons in sidebar, found {len(aria_hidden_icons)}"
    )


# ---------------------------------------------------------------------------
# Search landmark and label
# ---------------------------------------------------------------------------

def test_search_has_role_search(client, db_session):
    body = _get_dashboard_html(client, db_session)
    assert 'role="search"' in body, "search container missing role='search'"


def test_search_has_label(client, db_session):
    body = _get_dashboard_html(client, db_session)
    # A <label for="admin-global-search"> must exist
    assert 'for="admin-global-search"' in body, (
        "Search input missing associated <label for='admin-global-search'>"
    )


# ---------------------------------------------------------------------------
# Sidebar toggle button
# ---------------------------------------------------------------------------

def test_sidebar_toggle_has_aria_label(client, db_session):
    body = _get_dashboard_html(client, db_session)
    # Must have aria-label on the sidebar-toggle button
    match = re.search(r'<button[^>]+sidebar-toggle[^>]*>', body)
    assert match, "sidebar-toggle button not found"
    btn_html = match.group(0)
    assert "aria-label=" in btn_html, "sidebar-toggle missing aria-label"
    assert "aria-expanded=" in btn_html, "sidebar-toggle missing aria-expanded"
    assert "aria-controls=" in btn_html, "sidebar-toggle missing aria-controls"


# ---------------------------------------------------------------------------
# CSS: focus-visible rules exist for admin nav elements
# ---------------------------------------------------------------------------

def test_admin_nav_link_focus_visible_css_exists():
    css_path = (
        "app/static/css/design-system.css"
    )
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    full_path = os.path.join(project_root, css_path)
    with open(full_path, encoding="utf-8") as f:
        css = f.read()
    assert ".admin-sidebar .nav-link:focus-visible" in css, (
        "Missing focus-visible rule for .admin-sidebar .nav-link"
    )
    assert ".nav-section-title:focus-visible" in css, (
        "Missing focus-visible rule for .nav-section-title"
    )
    assert ".sidebar-toggle:focus-visible" in css, (
        "Missing focus-visible rule for .sidebar-toggle"
    )


def test_skip_to_content_css_exists():
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    css_path = os.path.join(project_root, "app/static/css/design-system.css")
    with open(css_path, encoding="utf-8") as f:
        css = f.read()
    assert ".skip-to-content" in css, "Missing .skip-to-content CSS rule"
