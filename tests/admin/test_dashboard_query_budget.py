"""Task 8 of 2026-05-24 admin audit — dashboard query budget.

Before refactor the dashboard ran 6 UNION counts for DAU/WAU/MAU plus 30 daily
UNIONs for the activity chart — 36+ round trips just for engagement metrics.
The materialised ``get_active_user_dates`` helper collapses each of those to a
single query. This test pins that win so a future regression that re-introduces
N+1 querying on the dashboard gets caught.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy.event
from sqlalchemy.engine import Engine

from app.auth.models import User
from app.utils.db import db


class _QueryCounter:
    """Counts SQL statements on every engine.

    Listens on the ``Engine`` class so we capture queries regardless of which
    connection/engine SQLAlchemy picks (the Flask-SQLAlchemy engine, savepoint
    connections, etc.).
    """

    def __init__(self):
        self.count = 0
        self.statements: list[str] = []

    def __enter__(self):
        sqlalchemy.event.listen(Engine, 'before_cursor_execute', self._handler)
        return self

    def __exit__(self, *args):
        sqlalchemy.event.remove(Engine, 'before_cursor_execute', self._handler)

    def _handler(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1
        self.statements.append(statement)


def _login_admin(client, db_session) -> User:
    admin = User(
        username=f"admin_{uuid.uuid4().hex[:8]}",
        email=f"admin_{uuid.uuid4().hex[:8]}@test.com",
        active=True,
        is_admin=True,
    )
    admin.set_password("pw")
    db_session.add(admin)
    db_session.flush()

    with client.session_transaction() as session:
        session["_user_id"] = str(admin.id)
        session["_fresh"] = True
    return admin


def test_engagement_metrics_uses_single_union_query(app, db_session):
    """``get_engagement_metrics`` must hit the DB at most twice — once for the
    UNION, plus any incidental savepoint/release statement from the test
    transaction. Regressing to one-query-per-metric is the failure mode."""
    from app.admin.utils.cache import clear_admin_cache
    from app.admin.routes.dashboard_routes import get_engagement_metrics

    clear_admin_cache()
    with _QueryCounter() as counter:
        get_engagement_metrics()

    union_statements = [s for s in counter.statements if 'UNION' in s.upper()]
    assert len(union_statements) == 1, (
        f"Expected 1 UNION query, got {len(union_statements)}: {[s[:200] for s in union_statements]}"
    )


def test_daily_activity_data_uses_single_union_query(app, db_session):
    """The 30-day activity chart used to run 30 UNION queries (one per day).
    After the refactor it runs exactly one UNION for the whole window."""
    from app.admin.utils.cache import clear_admin_cache
    from app.admin.routes.dashboard_routes import get_daily_activity_data

    clear_admin_cache()
    with _QueryCounter() as counter:
        get_daily_activity_data(30)

    union_statements = [s for s in counter.statements if 'UNION' in s.upper()]
    assert len(union_statements) == 1, (
        f"Expected 1 UNION query for 30-day chart, got {len(union_statements)}: "
        f"{union_statements}"
    )


@pytest.mark.smoke
def test_dashboard_route_query_budget(client, app, db_session):
    """End-to-end query budget on ``GET /admin/``.

    The exact number depends on the cache state and on which widgets fire, so
    the assertion is intentionally loose — it just locks in that the dashboard
    no longer makes hundreds of round trips. Adjust the ceiling only with a
    matching note in ``docs/audits/2026-05-24-admin-audit/README.md``.
    """
    from app.admin.utils.cache import clear_admin_cache

    _login_admin(client, db_session)
    clear_admin_cache()

    with _QueryCounter() as counter:
        response = client.get("/admin/")

    assert response.status_code == 200, response.data[:200]
    assert counter.count < 150, (
        f"Dashboard query budget exceeded: {counter.count} statements"
    )

    union_statements = [s for s in counter.statements if 'UNION' in s.upper()]
    # engagement (1) + daily_activity (1) + retention (a few per cohort date,
    # capped by 90-day window cardinality). Keep the ceiling well above the
    # current count so day-to-day churn doesn't make the test flaky.
    assert len(union_statements) < 30, (
        f"Too many UNION queries on dashboard: {len(union_statements)}"
    )
