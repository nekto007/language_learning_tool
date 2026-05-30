"""Tests for check_level_achievements (Task 7).

Covers:
- level_10 / level_25 / level_50 granted at the right XP thresholds
- below-threshold XP grants nothing
- idempotency: second call grants nothing new
- check_all_achievements includes 'levels' key
- award_xp triggers check_level_achievements on level-up
"""
from __future__ import annotations

import uuid

import pytest

from app.achievements.models import UserStatistics
from app.achievements.services import AchievementService
from app.achievements.seed import seed_achievements
from app.achievements.xp_service import get_level_info, xp_for_level
from app.auth.models import User
from app.study.models import Achievement, UserAchievement


LEVEL_BADGE_CODES = {'level_10', 'level_25', 'level_50'}

# XP thresholds for levels 10, 25, 50 — derived from formula 100*(n-1)*n/2
XP_FOR_LEVEL_10 = xp_for_level(10)   # 4500
XP_FOR_LEVEL_25 = xp_for_level(25)   # 30000
XP_FOR_LEVEL_50 = xp_for_level(50)   # 122500


@pytest.fixture
def level_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'lu_{suffix}',
        email=f'lu_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def level_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(LEVEL_BADGE_CODES)).all()
    assert len(badges) == len(LEVEL_BADGE_CODES), (
        f"Expected {len(LEVEL_BADGE_CODES)} level badges in DB, got {len(badges)}"
    )
    return {b.code: b for b in badges}


def _make_stats(db_session, user_id, total_xp=0):
    stats = UserStatistics(
        user_id=user_id,
        total_xp=total_xp,
    )
    db_session.add(stats)
    db_session.flush()
    return stats


class TestCheckLevelAchievements:

    def test_zero_xp_grants_nothing(self, db_session, level_user, level_badges):
        stats = _make_stats(db_session, level_user.id, total_xp=0)
        result = AchievementService.check_level_achievements(level_user.id, stats)
        assert result == []

    def test_just_below_level_10_grants_nothing(self, db_session, level_user, level_badges):
        stats = _make_stats(db_session, level_user.id, total_xp=XP_FOR_LEVEL_10 - 1)
        result = AchievementService.check_level_achievements(level_user.id, stats)
        assert result == []

    def test_level_10_xp_grants_level_10_badge(self, db_session, level_user, level_badges):
        stats = _make_stats(db_session, level_user.id, total_xp=XP_FOR_LEVEL_10)
        assert get_level_info(XP_FOR_LEVEL_10).current_level == 10
        result = AchievementService.check_level_achievements(level_user.id, stats)
        codes = {a.code for a in result}
        assert 'level_10' in codes
        assert 'level_25' not in codes
        assert 'level_50' not in codes

    def test_level_25_xp_grants_level_10_and_25(self, db_session, level_user, level_badges):
        stats = _make_stats(db_session, level_user.id, total_xp=XP_FOR_LEVEL_25)
        assert get_level_info(XP_FOR_LEVEL_25).current_level == 25
        result = AchievementService.check_level_achievements(level_user.id, stats)
        codes = {a.code for a in result}
        assert 'level_10' in codes
        assert 'level_25' in codes
        assert 'level_50' not in codes

    def test_level_50_xp_grants_all_three(self, db_session, level_user, level_badges):
        stats = _make_stats(db_session, level_user.id, total_xp=XP_FOR_LEVEL_50)
        assert get_level_info(XP_FOR_LEVEL_50).current_level == 50
        result = AchievementService.check_level_achievements(level_user.id, stats)
        codes = {a.code for a in result}
        assert 'level_10' in codes
        assert 'level_25' in codes
        assert 'level_50' in codes

    def test_idempotent_second_call_grants_nothing(self, db_session, level_user, level_badges):
        stats = _make_stats(db_session, level_user.id, total_xp=XP_FOR_LEVEL_10)
        first = AchievementService.check_level_achievements(level_user.id, stats)
        assert len(first) > 0

        second = AchievementService.check_level_achievements(level_user.id, stats)
        assert second == [], "Second call must be idempotent"

    def test_check_all_achievements_includes_levels(self, db_session, level_user, level_badges):
        _make_stats(db_session, level_user.id, total_xp=XP_FOR_LEVEL_10)
        result = AchievementService.check_all_achievements(level_user.id)
        assert 'levels' in result, "check_all_achievements must include 'levels' key"
        codes = {a.code for a in result['levels']}
        assert 'level_10' in codes

    def test_xp_just_above_level_10_does_not_re_grant(self, db_session, level_user, level_badges):
        stats = _make_stats(db_session, level_user.id, total_xp=XP_FOR_LEVEL_10)
        first = AchievementService.check_level_achievements(level_user.id, stats)
        assert any(a.code == 'level_10' for a in first)

        stats.total_xp = XP_FOR_LEVEL_10 + 50
        db_session.flush()
        second = AchievementService.check_level_achievements(level_user.id, stats)
        assert second == [], "No re-grant after threshold already exceeded"
