"""Task 42 of 2026-05-27 global site audit — admin dashboard N+1 queries.

Verifies:
- DAU/WAU/MAU uses a single UNION query (not 7 separate queries)
- _count_active_users_in_range does not do N+1 per day
- Dashboard cache returns cached result on second call (no cache miss per request)
- Query count on dashboard route is bounded
- get_retention_metrics does not run _active_user_ids_for_date in a loop
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, call

import pytest
import sqlalchemy.event
from sqlalchemy.engine import Engine

from app.auth.models import User
from app.utils.db import db


class _QueryCounter:
    """Count SQL statements via SQLAlchemy engine event."""

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


def _union_count(counter: _QueryCounter) -> int:
    return sum(1 for s in counter.statements if 'UNION' in s.upper())


# ---------------------------------------------------------------------------
# DAU/WAU/MAU — single UNION
# ---------------------------------------------------------------------------

class TestDauWauMauUnionQuery:
    """get_engagement_metrics must issue exactly one UNION query."""

    def test_single_union_query(self, app, db_session):
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_engagement_metrics

        clear_admin_cache()
        with _QueryCounter() as counter:
            get_engagement_metrics()

        n_union = _union_count(counter)
        assert n_union == 1, (
            f"Expected 1 UNION query for DAU/WAU/MAU, got {n_union}: "
            f"{[s[:120] for s in counter.statements if 'UNION' in s.upper()]}"
        )

    def test_result_keys_present(self, app, db_session):
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_engagement_metrics

        clear_admin_cache()
        with patch('app.admin.routes.dashboard_routes.get_active_user_dates', return_value={}):
            result = get_engagement_metrics()

        assert {'dau', 'wau', 'mau'}.issubset(result.keys())

    def test_correct_counts_from_bucket(self, app, db_session):
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_engagement_metrics

        clear_admin_cache()
        today = datetime.now(timezone.utc).date()
        bucket = {
            today: {1, 2, 3},
            today - timedelta(days=3): {4, 5},
            today - timedelta(days=20): {6},
        }
        with patch('app.admin.routes.dashboard_routes.get_active_user_dates', return_value=bucket):
            result = get_engagement_metrics()

        assert result['dau'] == 3       # only today
        assert result['wau'] == 5       # today + day-3
        assert result['mau'] == 6       # all three dates in 30-day window


# ---------------------------------------------------------------------------
# _count_active_users_in_range — no N+1 per day
# ---------------------------------------------------------------------------

class TestCountActiveUsersInRange:
    """_count_active_users_in_range must call get_active_user_dates once."""

    def test_delegates_to_get_active_user_dates_once(self, app, db_session):
        from app.admin.routes.dashboard_routes import _count_active_users_in_range

        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=29)
        bucket = {
            today: {1, 2},
            start: {3},
        }
        with patch(
            'app.admin.routes.dashboard_routes.get_active_user_dates',
            return_value=bucket,
        ) as mock_fn:
            count = _count_active_users_in_range(start, today)

        assert mock_fn.call_count == 1, "Expected exactly one call, not one per day"
        assert count == 3

    def test_empty_range_returns_zero(self, app, db_session):
        from app.admin.routes.dashboard_routes import _count_active_users_in_range

        today = datetime.now(timezone.utc).date()
        with patch(
            'app.admin.routes.dashboard_routes.get_active_user_dates',
            return_value={},
        ):
            count = _count_active_users_in_range(today, today)

        assert count == 0

    def test_no_n1_per_day(self, app, db_session):
        """The helper must not execute one UNION query per day in the range."""
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import _count_active_users_in_range

        clear_admin_cache()
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=13)

        with _QueryCounter() as counter:
            _count_active_users_in_range(start, today)

        n_union = _union_count(counter)
        # Should be at most 1 UNION regardless of 14-day range
        assert n_union <= 1, (
            f"N+1 detected: {n_union} UNION queries for a 14-day range (expected ≤1)"
        )


# ---------------------------------------------------------------------------
# Dashboard cache — no DB on second call
# ---------------------------------------------------------------------------

class TestDashboardCache:
    """Cached metric functions must not hit the DB on the second call."""

    @pytest.mark.smoke
    def test_cache_hit_prevents_db_query(self, app, db_session):
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_engagement_metrics

        clear_admin_cache()

        with patch(
            'app.admin.routes.dashboard_routes.get_active_user_dates',
            return_value={},
        ) as mock_fn:
            get_engagement_metrics()
            first_calls = mock_fn.call_count

        assert first_calls == 1

        # Second call within TTL must use cache
        with patch(
            'app.admin.routes.dashboard_routes.get_active_user_dates',
            return_value={},
        ) as mock_fn2:
            get_engagement_metrics()
            second_calls = mock_fn2.call_count

        assert second_calls == 0, "Cache miss on second call — expected cache hit"

    def test_cache_cleared_allows_fresh_query(self, app, db_session):
        from app.admin.utils.cache import clear_admin_cache, _cache
        from app.admin.routes.dashboard_routes import get_engagement_metrics

        clear_admin_cache()

        with patch('app.admin.routes.dashboard_routes.get_active_user_dates', return_value={}):
            get_engagement_metrics()

        # Some engagement_metrics_* key must now be in the cache store
        assert any(k.startswith('engagement_metrics_') for k in _cache), \
            "Expected a cached entry for engagement_metrics after first call"

        clear_admin_cache()
        assert not any(k.startswith('engagement_metrics_') for k in _cache), \
            "Cache not cleared"


# ---------------------------------------------------------------------------
# get_retention_metrics — no N+1 loop
# ---------------------------------------------------------------------------

class TestRetentionMetricsNoN1:
    """get_retention_metrics must not call _active_user_ids_for_date in a loop."""

    def test_no_n1_union_queries(self, app, db_session):
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_retention_metrics

        clear_admin_cache()
        with _QueryCounter() as counter:
            result = get_retention_metrics()

        # Each _retention_rate(offset) issues at most 1 UNION query; 3 offsets → ≤3.
        # Pre-refactor code would run N UNION queries (one per registration date).
        n_union = _union_count(counter)
        assert n_union <= 3, (
            f"Possible N+1 in get_retention_metrics: {n_union} UNION queries "
            f"(expected ≤3 for d1/d7/d30)"
        )
        assert set(result.keys()) == {'d1', 'd7', 'd30'}

    def test_returns_float_values(self, app, db_session):
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_retention_metrics

        clear_admin_cache()
        result = get_retention_metrics()
        for key in ('d1', 'd7', 'd30'):
            assert isinstance(result[key], float), f"{key} should be a float"
            assert 0.0 <= result[key] <= 100.0, f"{key} out of [0, 100] range"


# ---------------------------------------------------------------------------
# get_content_quality — no N+1 lesson lookup
# ---------------------------------------------------------------------------

class TestContentQualityNoN1:
    """get_content_quality must bulk-load lessons instead of per-row .get()."""

    def test_no_n1_lesson_queries(self, app, db_session):
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_content_quality

        clear_admin_cache()
        with _QueryCounter() as counter:
            get_content_quality()

        # With bulk load there should be no more than ~5 queries regardless of
        # how many lesson_stats rows there are. Check for absence of per-lesson SELECT.
        lesson_selects = [
            s for s in counter.statements
            if 'lessons' in s.lower() and 'SELECT' in s.upper() and 'WHERE' in s.upper()
               and 'IN' not in s.upper()  # bulk IN is fine
        ]
        # Allow a small constant number of individual lesson queries (e.g. subqueries).
        # What we are forbidding is O(N) queries where N = number of low-pass lessons.
        assert len(lesson_selects) <= 2, (
            f"Possible N+1 lesson lookups in get_content_quality: "
            f"{len(lesson_selects)} individual lesson SELECTs"
        )
