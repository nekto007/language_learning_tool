"""Task 7 of 2026-05-24 admin audit — dashboard_admin sub-blueprint.

Dashboard, stats, and content-quality routes were split out of
``app/admin/main_routes.py`` into ``app/admin/routes/dashboard_routes.py`` to
shrink the monolithic admin module. This test pins the new structure so a
future regression that re-attaches the routes to the wrong blueprint (or
silently drops one) gets caught.
"""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User


EXPECTED_DASHBOARD_ENDPOINTS = (
    ("dashboard_admin.dashboard", "/admin/"),
    ("dashboard_admin.content_quality_page", "/admin/content-quality"),
    ("dashboard_admin.content_quality_export", "/admin/content-quality/export"),
)


def test_dashboard_endpoints_registered_on_new_blueprint(app):
    """The three moved routes must live on ``dashboard_admin``, not ``admin``."""
    rules = {rule.endpoint: rule.rule for rule in app.url_map.iter_rules()}

    for endpoint, url in EXPECTED_DASHBOARD_ENDPOINTS:
        assert endpoint in rules, f"missing endpoint {endpoint}"
        assert rules[endpoint] == url

    # The legacy aliases must NOT linger on the ``admin`` blueprint, otherwise
    # url_for('admin.dashboard') will silently keep resolving to a stale view.
    for legacy in ("admin.dashboard", "admin.content_quality_page",
                   "admin.content_quality_export"):
        assert legacy not in rules, f"legacy endpoint {legacy} should be gone"


def test_dashboard_module_exposes_5xx_counter():
    """``app/__init__.py`` imports ``increment_5xx_counter`` from the new module."""
    from app.admin.routes import dashboard_routes

    assert callable(dashboard_routes.increment_5xx_counter)
    before = dashboard_routes._error_5xx_count
    dashboard_routes.increment_5xx_counter()
    assert dashboard_routes._error_5xx_count == before + 1


def test_main_routes_no_longer_owns_dashboard_helpers():
    """Helpers that moved to ``dashboard_routes`` must not still be in ``main_routes``."""
    from app.admin import main_routes

    for name in (
        "get_dashboard_statistics",
        "get_engagement_metrics",
        "get_system_health",
        "_active_user_ids_for_date",
        "_count_active_users_in_range",
        "increment_5xx_counter",
    ):
        assert not hasattr(main_routes, name), (
            f"main_routes still exposes {name}; should have moved to dashboard_routes"
        )


@pytest.mark.smoke
def test_dashboard_route_renders_for_admin(client, app, db_session):
    """Smoke-test the moved ``/admin/`` route end-to-end for an admin session."""
    admin_user = User(
        username=f"admin_{uuid.uuid4().hex[:8]}",
        email=f"admin_{uuid.uuid4().hex[:8]}@test.com",
        active=True,
        is_admin=True,
    )
    admin_user.set_password("pw")
    db_session.add(admin_user)
    db_session.flush()

    with client.session_transaction() as session:
        session["_user_id"] = str(admin_user.id)
        session["_fresh"] = True

    response = client.get("/admin/")
    assert response.status_code == 200
