"""Tests for DAU/WAU caching on get_engagement_metrics."""
from unittest.mock import patch

import pytest


class TestEngagementMetricsCache:
    """Verify that get_engagement_metrics caches DAU/WAU results."""

    def test_second_call_hits_cache(self, app, db_session):
        """Second call within TTL must not invoke get_active_user_dates again."""
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_engagement_metrics

        clear_admin_cache()

        with patch(
            'app.admin.routes.dashboard_routes.get_active_user_dates',
            return_value={},
        ) as mock_first:
            get_engagement_metrics()
            first_calls = mock_first.call_count

        assert first_calls == 1, (
            f"Expected exactly one materialised UNION call after refactor, got {first_calls}"
        )

        with patch(
            'app.admin.routes.dashboard_routes.get_active_user_dates',
            return_value={'should_not_be_used': 99},
        ) as mock_second:
            result_cached = get_engagement_metrics()
            second_calls = mock_second.call_count

        assert second_calls == 0, (
            f"Expected 0 DB calls on cached second invocation, got {second_calls}"
        )
        # Result should be the first (cached) data; if the second mock had run,
        # _count() would have raised because the bucket key isn't a date object.
        assert result_cached['dau'] == 0

    @pytest.mark.smoke
    def test_engagement_metrics_returns_expected_keys(self, app, db_session):
        """get_engagement_metrics returns dict with dau/wau/mau keys."""
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_engagement_metrics

        clear_admin_cache()

        with patch(
            'app.admin.routes.dashboard_routes.get_active_user_dates',
            return_value={},
        ):
            result = get_engagement_metrics()

        expected_keys = {'dau', 'wau', 'mau', 'dau_trend', 'wau_trend', 'mau_trend'}
        assert expected_keys.issubset(result.keys())

    def test_engagement_metrics_aggregates_from_single_bucket(self, app, db_session):
        """A single materialised bucket is enough to compute dau/wau/mau + prev_* in Python."""
        from datetime import datetime, timedelta, timezone

        from app.admin.utils.cache import clear_admin_cache
        from app.admin.routes.dashboard_routes import get_engagement_metrics

        clear_admin_cache()
        today = datetime.now(timezone.utc).date()
        bucket = {
            today: {1, 2, 3},
            today - timedelta(days=1): {2, 4},
            today - timedelta(days=10): {5},
            today - timedelta(days=40): {6},
        }
        with patch(
            'app.admin.routes.dashboard_routes.get_active_user_dates',
            return_value=bucket,
        ) as mock_helper:
            result = get_engagement_metrics()

        assert mock_helper.call_count == 1
        assert result['dau'] == 3                   # today: {1,2,3}
        assert result['wau'] == 4                   # 7-day window: {1,2,3,4}
        assert result['mau'] == 5                   # 30-day window: {1,2,3,4,5}
        assert result['dau_trend_value'] != ''      # prev_dau was 2 → trend computed

    def test_leaderboard_cache_ttl_is_5_minutes(self, app, db_session):
        """Verify leaderboard cache TTL constant is 300 seconds (5 min)."""
        import app.words.routes as words_routes
        # The cache timeout is 300 seconds (5 min) — verified via constant in cache update
        cache = words_routes._leaderboard_cache
        assert 'expires' in cache
        assert 'data' in cache
        assert 'lock' in cache
        # The TTL used when setting cache is 300 (5 min) — confirmed in _get_cached_leaderboard
        import inspect
        src = inspect.getsource(words_routes._get_cached_leaderboard)
        assert '300' in src, "Expected 5-minute (300s) TTL in _get_cached_leaderboard"
