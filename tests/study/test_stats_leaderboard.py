"""Tests for Task 31: Study — SRS stats and leaderboard.

Covers:
- _get_cached_leaderboard TTL and staleness behaviour
- Leaderboard reads UserStatistics.total_xp (not legacy UserXP)
- stats_service graceful handling when UserStatistics row is absent
- get_level_info(0) returns level=1
"""
from __future__ import annotations

import time
import threading
import uuid
from unittest.mock import patch

import pytest

from app.achievements.models import UserStatistics
from app.auth.models import User
from app.utils.db import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db_session, xp: int | None = None) -> User:
    uid = uuid.uuid4().hex[:8]
    user = User(username=f"lb_{uid}", email=f"lb_{uid}@test.com")
    user.set_password("password")
    db_session.add(user)
    db_session.flush()
    if xp is not None:
        db_session.add(UserStatistics(user_id=user.id, total_xp=xp))
    return user


# ---------------------------------------------------------------------------
# get_level_info(0) returns level=1
# ---------------------------------------------------------------------------

class TestGetLevelInfoZero:
    def test_zero_xp_returns_level_1(self):
        from app.achievements.xp_service import get_level_info
        info = get_level_info(0)
        assert info.current_level == 1

    def test_none_xp_returns_level_1(self):
        from app.achievements.xp_service import get_level_info
        info = get_level_info(None)
        assert info.current_level == 1

    def test_negative_xp_returns_level_1(self):
        from app.achievements.xp_service import get_level_info
        info = get_level_info(-5)
        assert info.current_level == 1


# ---------------------------------------------------------------------------
# Leaderboard reads UserStatistics.total_xp
# ---------------------------------------------------------------------------

class TestLeaderboardReadsUserStatistics:
    @pytest.mark.smoke
    def test_xp_leaderboard_reads_user_statistics_total_xp(self, db_session):
        """get_xp_leaderboard returns total_xp from UserStatistics, not any legacy table."""
        from app.study.services.stats_service import StatsService

        user = _make_user(db_session, xp=9876)
        db_session.commit()

        leaderboard = StatsService.get_xp_leaderboard(limit=200)
        entry = next((e for e in leaderboard if e["id"] == user.id), None)

        assert entry is not None, "User with UserStatistics should appear in leaderboard"
        assert entry["total_xp"] == 9876

    def test_leaderboard_excludes_user_without_statistics_row(self, db_session):
        """Users who have no UserStatistics row are excluded (inner join)."""
        from app.study.services.stats_service import StatsService

        user_no_stats = _make_user(db_session, xp=None)
        db_session.commit()

        leaderboard = StatsService.get_xp_leaderboard(limit=500)
        ids = {e["id"] for e in leaderboard}

        assert user_no_stats.id not in ids, (
            "User without UserStatistics should not appear in leaderboard"
        )

    def test_leaderboard_entries_include_level_field(self, db_session):
        """Each leaderboard entry has a 'level' key computed from total_xp."""
        from app.study.services.stats_service import StatsService

        user = _make_user(db_session, xp=300)  # 300 XP = level 3
        db_session.commit()

        leaderboard = StatsService.get_xp_leaderboard(limit=200)
        entry = next((e for e in leaderboard if e["id"] == user.id), None)

        assert entry is not None
        assert "level" in entry
        assert entry["level"] == 3

    def test_leaderboard_sorted_descending_by_xp(self, db_session):
        """Leaderboard entries are sorted highest XP first."""
        from app.study.services.stats_service import StatsService

        for xp in [6001, 6003, 6002]:
            _make_user(db_session, xp=xp)
        db_session.commit()

        leaderboard = StatsService.get_xp_leaderboard(limit=500)
        xp_values = [e["total_xp"] for e in leaderboard]

        assert xp_values == sorted(xp_values, reverse=True)


# ---------------------------------------------------------------------------
# stats_service graceful handling when UserStatistics row is absent
# ---------------------------------------------------------------------------

class TestStatsServiceMissingUserStatistics:
    @pytest.mark.smoke
    def test_get_user_xp_rank_returns_none_for_user_without_statistics(self, db_session):
        """get_user_xp_rank returns None (not an exception) when UserStatistics absent."""
        from app.study.services.stats_service import StatsService

        user = _make_user(db_session, xp=None)
        db_session.commit()

        rank = StatsService.get_user_xp_rank(user.id)
        assert rank is None

    def test_get_user_xp_rank_returns_none_for_zero_xp(self, db_session):
        """get_user_xp_rank returns None when total_xp is 0 (falsy guard)."""
        from app.study.services.stats_service import StatsService

        user = _make_user(db_session, xp=0)
        db_session.commit()

        rank = StatsService.get_user_xp_rank(user.id)
        assert rank is None

    def test_get_user_xp_rank_returns_positive_int_for_user_with_xp(self, db_session):
        """get_user_xp_rank returns a positive integer when UserStatistics is present."""
        from app.study.services.stats_service import StatsService

        user = _make_user(db_session, xp=7777)
        db_session.commit()

        rank = StatsService.get_user_xp_rank(user.id)
        assert isinstance(rank, int)
        assert rank >= 1

    def test_get_xp_leaderboard_does_not_crash_with_empty_table(self, db_session):
        """get_xp_leaderboard returns empty list when no UserStatistics rows exist."""
        from app.study.services.stats_service import StatsService

        # Clear stats for all users (within this transaction only)
        db_session.query(UserStatistics).delete()
        db_session.flush()

        leaderboard = StatsService.get_xp_leaderboard(limit=10)
        assert isinstance(leaderboard, list)
        assert leaderboard == []


# ---------------------------------------------------------------------------
# _get_cached_leaderboard TTL and cache behaviour
# ---------------------------------------------------------------------------

class TestCachedLeaderboard:
    """Tests for _get_cached_leaderboard in app/words/routes.py."""

    def _reset_cache(self):
        from app.words import routes as words_routes
        cache = words_routes._leaderboard_cache
        with cache["lock"]:
            cache["data"] = None
            cache["expires"] = 0.0

    def test_returns_list(self, db_session):
        from app.words.routes import _get_cached_leaderboard
        from app.study.services.stats_service import StatsService

        self._reset_cache()
        result = _get_cached_leaderboard(StatsService, limit=5)
        assert isinstance(result, list)

    @pytest.mark.smoke
    def test_within_ttl_returns_same_object(self, db_session):
        """Two consecutive calls within TTL return the identical cached object."""
        from app.words.routes import _get_cached_leaderboard
        from app.study.services.stats_service import StatsService

        self._reset_cache()
        first = _get_cached_leaderboard(StatsService, limit=5)
        second = _get_cached_leaderboard(StatsService, limit=5)
        assert first is second, "Within TTL the same object should be returned from cache"

    def test_after_ttl_expiry_returns_fresh_data(self, db_session):
        """After TTL expires the cache returns fresh data (new object)."""
        from app.words.routes import _get_cached_leaderboard, _leaderboard_cache
        from app.study.services.stats_service import StatsService

        self._reset_cache()
        first = _get_cached_leaderboard(StatsService, limit=5)

        # Manually expire the cache
        with _leaderboard_cache["lock"]:
            _leaderboard_cache["expires"] = time.time() - 1.0

        second = _get_cached_leaderboard(StatsService, limit=5)
        # After TTL the function must query again; result is a new list
        assert isinstance(second, list)
        # The old cached reference should be different (cache was refreshed)
        assert second is not first

    def test_stale_data_not_returned_after_xp_update_once_ttl_expires(self, db_session):
        """After TTL expires the leaderboard reflects updated XP (not stale cache)."""
        from app.words.routes import _get_cached_leaderboard, _leaderboard_cache
        from app.study.services.stats_service import StatsService

        # Seed a user with 100 XP
        user = _make_user(db_session, xp=100)
        db_session.commit()

        self._reset_cache()
        first = _get_cached_leaderboard(StatsService, limit=500)
        entry_before = next((e for e in first if e["id"] == user.id), None)
        assert entry_before is not None
        assert entry_before["total_xp"] == 100

        # Update user XP in DB
        stats = UserStatistics.query.filter_by(user_id=user.id).first()
        stats.total_xp = 9999
        db_session.commit()

        # Force cache expiry
        with _leaderboard_cache["lock"]:
            _leaderboard_cache["expires"] = time.time() - 1.0

        second = _get_cached_leaderboard(StatsService, limit=500)
        entry_after = next((e for e in second if e["id"] == user.id), None)

        assert entry_after is not None
        assert entry_after["total_xp"] == 9999, (
            "After TTL expiry the leaderboard should reflect the updated XP value"
        )

    def test_concurrent_cache_miss_does_not_corrupt_data(self, app, db_session):
        """Concurrent threads filling an expired cache don't corrupt it."""
        from app.words.routes import _get_cached_leaderboard, _leaderboard_cache
        from app.study.services.stats_service import StatsService

        self._reset_cache()
        with _leaderboard_cache["lock"]:
            _leaderboard_cache["expires"] = time.time() - 1.0

        results = []
        errors = []

        def _call():
            with app.app_context():
                try:
                    results.append(_get_cached_leaderboard(StatsService, limit=5))
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=_call) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent cache access raised: {errors}"
        for r in results:
            assert isinstance(r, list)

    def test_invalidate_leaderboard_cache_expires_immediately(self, db_session):
        """invalidate_leaderboard_cache() expires the cache so the next read is fresh."""
        from app.words.routes import _get_cached_leaderboard, _leaderboard_cache, invalidate_leaderboard_cache
        from app.study.services.stats_service import StatsService

        self._reset_cache()
        # Populate cache with a fresh call
        _get_cached_leaderboard(StatsService, limit=5)
        assert _leaderboard_cache['data'] is not None
        assert _leaderboard_cache['expires'] > time.time()

        invalidate_leaderboard_cache()

        # After invalidation the TTL must be in the past (or zero)
        assert _leaderboard_cache['expires'] <= time.time(), (
            "Cache should be expired immediately after invalidate_leaderboard_cache()"
        )

    @pytest.mark.smoke
    def test_award_xp_triggers_cache_invalidation(self, db_session):
        """award_xp() calls invalidate_leaderboard_cache() so stale data is not served."""
        from app.words.routes import _leaderboard_cache, _get_cached_leaderboard
        from app.study.services.stats_service import StatsService
        from app.achievements.xp_service import award_xp

        user = _make_user(db_session, xp=50)
        db_session.commit()

        self._reset_cache()
        # Prime the cache
        _get_cached_leaderboard(StatsService, limit=5)
        assert _leaderboard_cache['expires'] > time.time()

        # award_xp should expire the leaderboard cache
        award_xp(user.id, 10, 'test_source')

        assert _leaderboard_cache['expires'] <= time.time(), (
            "award_xp should have expired the leaderboard cache"
        )
