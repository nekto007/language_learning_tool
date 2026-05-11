"""Tests for plan streak milestone notifications — Task 97."""
import uuid
from datetime import date, datetime

import pytest

from app.auth.models import User
from app.notifications.models import Notification
from app.notifications.services import (
    check_plan_streak_milestone_notification,
    notify_plan_streak_milestone,
    PLAN_STREAK_MILESTONE_DAYS,
)


@pytest.fixture
def milestone_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'ms_{suffix}',
        email=f'ms_{suffix}@test.com',
        active=True,
        onboarding_completed=True,
    )
    user.set_password('test')
    db_session.add(user)
    db_session.commit()
    return user


class TestPlanStreakMilestoneDays:
    def test_milestone_days_are_7_30_100(self):
        assert PLAN_STREAK_MILESTONE_DAYS == {7, 30, 100}


class TestNotifyPlanStreakMilestone:
    def test_creates_notification_when_pref_on(self, milestone_user, db_session):
        milestone_user.notify_in_app_achievements = True
        db_session.commit()

        result = notify_plan_streak_milestone(milestone_user.id, 7)
        db_session.commit()

        assert result is not None
        assert result.type == 'plan_streak_milestone'
        assert '7' in result.title

    def test_blocked_when_pref_off(self, milestone_user, db_session):
        milestone_user.notify_in_app_achievements = False
        db_session.commit()

        result = notify_plan_streak_milestone(milestone_user.id, 7)

        assert result is None

    def test_uses_achievement_pref_not_streak_pref(self, milestone_user, db_session):
        # notify_in_app_achievements controls plan_streak_milestone
        milestone_user.notify_in_app_achievements = True
        milestone_user.notify_in_app_streaks = False
        db_session.commit()

        result = notify_plan_streak_milestone(milestone_user.id, 30)
        db_session.commit()

        assert result is not None
        assert result.type == 'plan_streak_milestone'


class TestCheckPlanStreakMilestoneNotification:
    def test_streak_7_creates_notification(self, milestone_user, db_session):
        milestone_user.notify_in_app_achievements = True
        db_session.commit()

        plan_date = date.today()
        check_plan_streak_milestone_notification(milestone_user.id, 7, plan_date)
        db_session.commit()

        notifs = Notification.query.filter_by(
            user_id=milestone_user.id, type='plan_streak_milestone'
        ).all()
        assert len(notifs) == 1
        assert '7' in notifs[0].title

    def test_streak_30_creates_notification(self, milestone_user, db_session):
        milestone_user.notify_in_app_achievements = True
        db_session.commit()

        check_plan_streak_milestone_notification(milestone_user.id, 30, date.today())
        db_session.commit()

        notifs = Notification.query.filter_by(
            user_id=milestone_user.id, type='plan_streak_milestone'
        ).all()
        assert len(notifs) == 1
        assert '30' in notifs[0].title

    def test_streak_100_creates_notification(self, milestone_user, db_session):
        milestone_user.notify_in_app_achievements = True
        db_session.commit()

        check_plan_streak_milestone_notification(milestone_user.id, 100, date.today())
        db_session.commit()

        notifs = Notification.query.filter_by(
            user_id=milestone_user.id, type='plan_streak_milestone'
        ).all()
        assert len(notifs) == 1

    def test_non_milestone_streak_creates_nothing(self, milestone_user, db_session):
        milestone_user.notify_in_app_achievements = True
        db_session.commit()

        for streak in [1, 5, 14, 50, 60, 99]:
            check_plan_streak_milestone_notification(milestone_user.id, streak, date.today())
        db_session.commit()

        notifs = Notification.query.filter_by(
            user_id=milestone_user.id, type='plan_streak_milestone'
        ).all()
        assert len(notifs) == 0

    def test_dedup_same_day_no_duplicate(self, milestone_user, db_session):
        milestone_user.notify_in_app_achievements = True
        db_session.commit()

        plan_date = date.today()
        # Call twice on same day
        check_plan_streak_milestone_notification(milestone_user.id, 7, plan_date)
        db_session.commit()
        check_plan_streak_milestone_notification(milestone_user.id, 7, plan_date)
        db_session.commit()

        notifs = Notification.query.filter_by(
            user_id=milestone_user.id, type='plan_streak_milestone'
        ).all()
        assert len(notifs) == 1

    def test_flag_false_no_notification(self, milestone_user, db_session):
        milestone_user.notify_in_app_achievements = False
        db_session.commit()

        check_plan_streak_milestone_notification(milestone_user.id, 7, date.today())
        db_session.commit()

        notifs = Notification.query.filter_by(
            user_id=milestone_user.id, type='plan_streak_milestone'
        ).all()
        assert len(notifs) == 0

    def test_streak_zero_creates_nothing(self, milestone_user, db_session):
        milestone_user.notify_in_app_achievements = True
        db_session.commit()

        check_plan_streak_milestone_notification(milestone_user.id, 0, date.today())
        db_session.commit()

        notifs = Notification.query.filter_by(
            user_id=milestone_user.id, type='plan_streak_milestone'
        ).all()
        assert len(notifs) == 0
