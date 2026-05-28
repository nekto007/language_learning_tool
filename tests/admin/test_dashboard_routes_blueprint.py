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


def test_5xx_counter_increments_via_error_handler(app):
    """The 500 error handler in __init__.py must call increment_5xx_counter."""
    from app.admin.routes import dashboard_routes

    before = dashboard_routes._error_5xx_count

    with app.test_request_context('/'):
        # Flask stores 500 handlers keyed by (None, 500, None) in Werkzeug's
        # error_handler_spec.  Invoke it directly to verify the counter path.
        handlers_500 = app.error_handler_spec.get(None, {}).get(500, {})
        # There should be exactly one handler registered for 500 (None key = catch-all).
        assert handlers_500, "No 500 error handler registered"
        handler_fn = next(iter(handlers_500.values()))
        handler_fn(Exception('boom'))

    assert dashboard_routes._error_5xx_count == before + 1
    # Restore counter to avoid polluting other tests.
    dashboard_routes._error_5xx_count = before


def test_get_system_health_includes_db_pool_field(app):
    """get_system_health should include db_pool key (may be None for test pool)."""
    from app.admin.routes.dashboard_routes import get_system_health
    from app.admin.utils.cache import _cache

    # Clear cached value so we get a fresh call.
    _cache.pop('system_health', None)

    with app.app_context():
        health = get_system_health()

    assert 'db_pool' in health
    # In the test env we use StaticPool which may not support size()/checkedin(),
    # so db_pool may be None — that is acceptable.
    if health['db_pool'] is not None:
        for key in ('size', 'checked_in', 'checked_out', 'overflow'):
            assert key in health['db_pool'], f"db_pool missing '{key}'"

    # Cleanup cached value.
    _cache.pop('system_health', None)


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
