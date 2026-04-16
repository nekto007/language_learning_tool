"""Tests for DAU/WAU caching on get_engagement_metrics."""
from unittest.mock import patch

import pytest


class TestEngagementMetricsCache:
    """Verify that get_engagement_metrics caches DAU/WAU results."""

    def test_second_call_hits_cache(self, app, db_session):
        """Second call within TTL must not invoke _count_active_users_in_range again."""
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.main_routes import get_engagement_metrics

        clear_admin_cache()

        dummy = {
            'dau': 1, 'dau_trend': '', 'dau_trend_value': '',
            'wau': 2, 'wau_trend': '', 'wau_trend_value': '',
            'mau': 3, 'mau_trend': '', 'mau_trend_value': '',
        }

        with patch(
            'app.admin.main_routes._count_active_users_in_range',
            return_value=1,
        ) as mock_count:
            result1 = get_engagement_metrics()
            result2 = get_engagement_metrics()

        # _count_active_users_in_range is called 6 times on first call (dau, wau, mau + prev each),
        # and 0 times on second call because the result is cached.
        call_count = mock_count.call_count
        assert call_count > 0, "Expected at least one DB call on first invocation"

        # On second call no new DB calls should happen (cache hit)
        # Re-run with fresh mock to confirm cache was set
        clear_admin_cache()

        with patch(
            'app.admin.main_routes._count_active_users_in_range',
            return_value=1,
        ) as mock_first:
            get_engagement_metrics()
            first_calls = mock_first.call_count

        with patch(
            'app.admin.main_routes._count_active_users_in_range',
            return_value=99,
        ) as mock_second:
            result_cached = get_engagement_metrics()
            second_calls = mock_second.call_count

        assert second_calls == 0, (
            f"Expected 0 DB calls on cached second invocation, got {second_calls}"
        )
        # Result should be the first (cached) data, not the second mock's value
        assert result_cached['dau'] != 99, "Cached result should not use new mock value"

    @pytest.mark.smoke
    def test_engagement_metrics_returns_expected_keys(self, app, db_session):
        """get_engagement_metrics returns dict with dau/wau/mau keys."""
        from app.admin.utils.cache import clear_admin_cache
        from app.admin.main_routes import get_engagement_metrics

        clear_admin_cache()

        with patch(
            'app.admin.main_routes._count_active_users_in_range',
            return_value=0,
        ):
            result = get_engagement_metrics()

        expected_keys = {'dau', 'wau', 'mau', 'dau_trend', 'wau_trend', 'mau_trend'}
        assert expected_keys.issubset(result.keys())

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
