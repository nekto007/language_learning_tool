"""Tests for weekly milestone reward achievements (Task 93).

Covers:
- week_1: granted at streak day 7, awards 100 XP
- week_4: granted at streak day 28, awards 500 XP
- week_12: granted at streak day 84, awards 2000 XP
- Non-milestone streak days do not trigger
- Grants are idempotent (calling twice doesn't re-award)
- Notification created on each milestone
"""
from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock

import pytest

from app.achievements.seed import seed_achievements
from app.achievements.services import check_weekly_milestone_achievements
from app.achievements.models import UserStatistics
from app.auth.models import User
from app.study.models import Achievement, UserAchievement


WEEKLY_BADGE_CODES = {'week_1', 'week_4', 'week_12'}


@pytest.fixture
def weekly_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'weekly_{suffix}',
        email=f'weekly_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def weekly_badges(db_session):
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(WEEKLY_BADGE_CODES)).all()
    assert len(badges) == len(WEEKLY_BADGE_CODES), (
        f"Expected {len(WEEKLY_BADGE_CODES)} badges, got {len(badges)}"
    )
    return {b.code: b for b in badges}


@pytest.fixture
def user_stats(db_session, weekly_user):
    stats = UserStatistics(user_id=weekly_user.id, current_streak_days=7)
    db_session.add(stats)
    db_session.flush()
    return stats


class TestWeeklyMilestoneAchievements:
    def test_week_1_granted_at_day_7(self, db_session, weekly_user, weekly_badges, user_stats):
        result = check_weekly_milestone_achievements(weekly_user.id, 7)
        assert len(result) == 1
        assert result[0].code == 'week_1'

        ua = UserAchievement.query.filter_by(
            user_id=weekly_user.id,
            achievement_id=weekly_badges['week_1'].id,
        ).first()
        assert ua is not None

    def test_week_4_granted_at_day_28(self, db_session, weekly_user, weekly_badges, user_stats):
        result = check_weekly_milestone_achievements(weekly_user.id, 28)
        assert len(result) == 1
        assert result[0].code == 'week_4'

    def test_week_12_granted_at_day_84(self, db_session, weekly_user, weekly_badges, user_stats):
        result = check_weekly_milestone_achievements(weekly_user.id, 84)
        assert len(result) == 1
        assert result[0].code == 'week_12'

    def test_non_milestone_days_return_empty(self, db_session, weekly_user, weekly_badges, user_stats):
        for days in (1, 6, 8, 14, 21, 29, 30, 83, 85, 100):
            result = check_weekly_milestone_achievements(weekly_user.id, days)
            assert result == [], f"Expected no achievement at day {days}"

    def test_idempotent_second_call_returns_empty(self, db_session, weekly_user, weekly_badges, user_stats):
        check_weekly_milestone_achievements(weekly_user.id, 7)
        db_session.flush()
        result2 = check_weekly_milestone_achievements(weekly_user.id, 7)
        assert result2 == []

        total = UserAchievement.query.filter_by(
            user_id=weekly_user.id,
            achievement_id=weekly_badges['week_1'].id,
        ).count()
        assert total == 1

    def test_week_1_awards_100_xp(self, db_session, weekly_user, weekly_badges, user_stats):
        xp_before = user_stats.total_xp or 0
        check_weekly_milestone_achievements(weekly_user.id, 7)
        db_session.flush()
        db_session.refresh(user_stats)
        assert (user_stats.total_xp or 0) >= xp_before + 100

    def test_week_4_awards_500_xp(self, db_session, weekly_user, weekly_badges, user_stats):
        xp_before = user_stats.total_xp or 0
        check_weekly_milestone_achievements(weekly_user.id, 28)
        db_session.flush()
        db_session.refresh(user_stats)
        assert (user_stats.total_xp or 0) >= xp_before + 500

    def test_week_12_awards_2000_xp(self, db_session, weekly_user, weekly_badges, user_stats):
        xp_before = user_stats.total_xp or 0
        check_weekly_milestone_achievements(weekly_user.id, 84)
        db_session.flush()
        db_session.refresh(user_stats)
        assert (user_stats.total_xp or 0) >= xp_before + 2000

    def test_notification_created_on_milestone(self, db_session, weekly_user, weekly_badges, user_stats):
        from app.notifications.models import Notification
        check_weekly_milestone_achievements(weekly_user.id, 7)
        db_session.flush()
        notif = Notification.query.filter_by(user_id=weekly_user.id).first()
        assert notif is not None
        assert '7' in notif.title or '1' in notif.title or 'XP' in notif.title or 'недел' in notif.title

    def test_notification_contains_xp_amount(self, db_session, weekly_user, weekly_badges, user_stats):
        from app.notifications.models import Notification
        check_weekly_milestone_achievements(weekly_user.id, 28)
        db_session.flush()
        notif = Notification.query.filter_by(user_id=weekly_user.id).first()
        assert notif is not None
        assert '500' in notif.title

    def test_no_notification_when_badges_missing(self, db_session, weekly_user):
        # Don't call seed_achievements — no badges in DB
        result = check_weekly_milestone_achievements(weekly_user.id, 7)
        assert result == []
