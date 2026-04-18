"""Unit tests for mission-specific badge check logic."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.achievements.seed import seed_achievements
from app.achievements.services import AchievementService
from app.auth.models import User
from app.notifications.models import Notification
from app.study.models import Achievement, UserAchievement


MISSION_BADGE_CODES = {
    'mission_first',
    'mission_progress_5',
    'mission_repair_5',
    'mission_reading_5',
    'mission_week_perfect',
    'mission_early_bird',
    'mission_night_owl',
    'mission_variety_3',
    'mission_speed_demon',
}


@pytest.fixture
def mission_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'mission_{suffix}',
        email=f'mission_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def mission_badges(db_session):
    """Seed daily-plan mission achievements."""
    seed_achievements()
    db_session.flush()
    badges = Achievement.query.filter(Achievement.code.in_(MISSION_BADGE_CODES)).all()
    assert len(badges) == len(MISSION_BADGE_CODES)
    return {b.code: b for b in badges}


def _record_day(db_session, user_id, day, mission_type, with_completion=True):
    """Record a `mission_selected` and optional `plan_completed` pair for day."""
    db_session.add(StreakEvent(
        user_id=user_id,
        event_type='mission_selected',
        coins_delta=0,
        event_date=day,
        details={'mission_type': mission_type},
    ))
    if with_completion:
        db_session.add(StreakEvent(
            user_id=user_id,
            event_type='plan_completed',
            coins_delta=0,
            event_date=day,
            details={'plans_completed_total': 1, 'rank_code': 'novice'},
        ))


# ---------------------------------------------------------------------------
# First completion
# ---------------------------------------------------------------------------


class TestMissionFirst:
    def test_first_completion_awards_mission_first(
        self, db_session, mission_user, mission_badges,
    ):
        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_first' in codes

        db_session.flush()
        assert UserAchievement.query.filter_by(
            user_id=mission_user.id,
            achievement_id=mission_badges['mission_first'].id,
        ).count() == 1

    def test_mission_first_not_reawarded(
        self, db_session, mission_user, mission_badges,
    ):
        AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 18, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_first' not in codes


# ---------------------------------------------------------------------------
# Mission type counts
# ---------------------------------------------------------------------------


class TestMissionTypeCounts:
    def test_five_progress_missions_award_progress_5(
        self, db_session, mission_user, mission_badges,
    ):
        today = date(2026, 4, 17)
        for offset in range(5):
            _record_day(
                db_session, mission_user.id,
                today - timedelta(days=offset + 1),
                'progress',
            )
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_progress_5' in codes

    def test_four_progress_missions_does_not_award(
        self, db_session, mission_user, mission_badges,
    ):
        today = date(2026, 4, 17)
        for offset in range(4):
            _record_day(
                db_session, mission_user.id,
                today - timedelta(days=offset + 1),
                'progress',
            )
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_progress_5' not in codes

    def test_repair_and_reading_counts_are_isolated(
        self, db_session, mission_user, mission_badges,
    ):
        today = date(2026, 4, 17)
        # 5 repair + 2 reading
        for offset in range(5):
            _record_day(
                db_session, mission_user.id,
                today - timedelta(days=offset + 1),
                'repair',
            )
        for offset in range(2):
            _record_day(
                db_session, mission_user.id,
                today - timedelta(days=offset + 10),
                'reading',
            )
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='repair',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_repair_5' in codes
        assert 'mission_reading_5' not in codes
        assert 'mission_progress_5' not in codes

    def test_selected_without_completion_does_not_count(
        self, db_session, mission_user, mission_badges,
    ):
        """mission_selected events for days lacking plan_completed shouldn't count."""
        today = date(2026, 4, 17)
        for offset in range(6):
            # selected-only (no completion) on past days
            _record_day(
                db_session, mission_user.id,
                today - timedelta(days=offset + 1),
                'progress',
                with_completion=False,
            )
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_progress_5' not in codes


# ---------------------------------------------------------------------------
# Perfect week
# ---------------------------------------------------------------------------


class TestPerfectWeek:
    def test_seven_consecutive_days_awards_week_perfect(
        self, db_session, mission_user, mission_badges,
    ):
        today = date(2026, 4, 17)
        for offset in range(7):
            _record_day(
                db_session, mission_user.id,
                today - timedelta(days=offset),
                'progress',
            )
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_week_perfect' in codes

    def test_gap_in_week_does_not_award(
        self, db_session, mission_user, mission_badges,
    ):
        today = date(2026, 4, 17)
        # Skip day offset=3
        for offset in (0, 1, 2, 4, 5, 6):
            _record_day(
                db_session, mission_user.id,
                today - timedelta(days=offset),
                'progress',
            )
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_week_perfect' not in codes


# ---------------------------------------------------------------------------
# Time-of-day badges
# ---------------------------------------------------------------------------


class TestTimeOfDayBadges:
    def test_before_9am_awards_early_bird(
        self, db_session, mission_user, mission_badges,
    ):
        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 7, 30, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_early_bird' in codes
        assert 'mission_night_owl' not in codes

    def test_at_9am_does_not_award_early_bird(
        self, db_session, mission_user, mission_badges,
    ):
        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_early_bird' not in codes

    def test_at_10pm_awards_night_owl(
        self, db_session, mission_user, mission_badges,
    ):
        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 22, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_night_owl' in codes
        assert 'mission_early_bird' not in codes

    def test_midday_awards_neither(
        self, db_session, mission_user, mission_badges,
    ):
        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 14, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_early_bird' not in codes
        assert 'mission_night_owl' not in codes

    def test_timezone_converts_utc_to_local(
        self, db_session, mission_user, mission_badges,
    ):
        """10:00 UTC == 07:00 America/Los_Angeles (before 9am local)."""
        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 14, 0, tzinfo=timezone.utc),
            tz='America/Los_Angeles',  # UTC-7 in April
        )
        codes = {a.code for a in awarded}
        # 14:00 UTC == 07:00 Los Angeles in April (DST)
        assert 'mission_early_bird' in codes


# ---------------------------------------------------------------------------
# Variety badge
# ---------------------------------------------------------------------------


class TestVarietyBadge:
    def test_three_types_in_week_awards_variety(
        self, db_session, mission_user, mission_badges,
    ):
        today = date(2026, 4, 17)
        _record_day(db_session, mission_user.id, today - timedelta(days=1), 'progress')
        _record_day(db_session, mission_user.id, today - timedelta(days=2), 'repair')
        _record_day(db_session, mission_user.id, today - timedelta(days=3), 'reading')
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_variety_3' in codes

    def test_two_types_does_not_award_variety(
        self, db_session, mission_user, mission_badges,
    ):
        today = date(2026, 4, 17)
        _record_day(db_session, mission_user.id, today - timedelta(days=1), 'progress')
        _record_day(db_session, mission_user.id, today - timedelta(days=2), 'repair')
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_variety_3' not in codes

    def test_three_types_outside_window_does_not_award(
        self, db_session, mission_user, mission_badges,
    ):
        today = date(2026, 4, 17)
        # All >= 7 days ago, outside the 7-day window
        _record_day(db_session, mission_user.id, today - timedelta(days=10), 'progress')
        _record_day(db_session, mission_user.id, today - timedelta(days=11), 'repair')
        _record_day(db_session, mission_user.id, today - timedelta(days=12), 'reading')
        db_session.flush()

        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_variety_3' not in codes


# ---------------------------------------------------------------------------
# Speed demon
# ---------------------------------------------------------------------------


class TestSpeedDemon:
    def test_under_30_minutes_awards_speed_demon(
        self, db_session, mission_user, mission_badges,
    ):
        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            duration_minutes=15,
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_speed_demon' in codes

    def test_exactly_30_minutes_does_not_award(
        self, db_session, mission_user, mission_badges,
    ):
        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            duration_minutes=30,
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_speed_demon' not in codes

    def test_duration_none_does_not_award(
        self, db_session, mission_user, mission_badges,
    ):
        awarded = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            duration_minutes=None,
            tz='UTC',
        )
        codes = {a.code for a in awarded}
        assert 'mission_speed_demon' not in codes


# ---------------------------------------------------------------------------
# Idempotency & notifications
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_repeat_calls_do_not_double_award(
        self, db_session, mission_user, mission_badges,
    ):
        completion = datetime(2026, 4, 17, 7, 30, tzinfo=timezone.utc)

        first = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=completion,
            duration_minutes=15,
            tz='UTC',
        )
        db_session.flush()
        first_codes = {a.code for a in first}
        assert {'mission_first', 'mission_early_bird', 'mission_speed_demon'} <= first_codes

        second = AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=completion,
            duration_minutes=15,
            tz='UTC',
        )
        assert second == []

        # UserAchievement rows are unique per (user, achievement)
        for code in ('mission_first', 'mission_early_bird', 'mission_speed_demon'):
            assert UserAchievement.query.filter_by(
                user_id=mission_user.id,
                achievement_id=mission_badges[code].id,
            ).count() == 1


class TestNotifications:
    def test_awarding_badges_creates_notification(
        self, db_session, mission_user, mission_badges,
    ):
        AchievementService.check_mission_achievements(
            user_id=mission_user.id,
            mission_type='progress',
            completion_time=datetime(2026, 4, 17, 13, 0, tzinfo=timezone.utc),
            tz='UTC',
        )
        db_session.flush()

        notifs = Notification.query.filter_by(
            user_id=mission_user.id, type='achievement',
        ).all()
        # At least one notification should have been created for mission_first
        assert any('Первая миссия' in (n.title or '') for n in notifs)


# ---------------------------------------------------------------------------
# Streak service integration
# ---------------------------------------------------------------------------


class TestStreakServiceIntegration:
    def test_full_plan_completion_triggers_mission_check(
        self, db_session, mission_user, mission_badges,
    ):
        from app.achievements.streak_service import process_streak_on_activity

        today = datetime.now(timezone.utc).date()
        db_session.add(StreakEvent(
            user_id=mission_user.id,
            event_type='mission_selected',
            coins_delta=0,
            event_date=today,
            details={'mission_type': 'progress'},
        ))
        db_session.flush()

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.achievements.streak_service.get_streak_status', return_value={
                 'streak': 1, 'coins_balance': 0, 'has_activity_today': True,
                 'can_repair': False, 'missed_date': None, 'repair_cost': None,
                 'required_steps': 1, 'steps_total': 4,
             }), \
             patch('app.achievements.streak_service.find_missed_date', return_value=None), \
             patch('app.achievements.streak_service.check_streak_milestone',
                   return_value=None):
            result = process_streak_on_activity(
                mission_user.id, steps_done=4, steps_total=4, tz='UTC',
            )

        assert result['steps_done'] == 4

        # mission_first should be awarded
        assert UserAchievement.query.filter_by(
            user_id=mission_user.id,
            achievement_id=mission_badges['mission_first'].id,
        ).count() == 1

    def test_already_completed_plan_does_not_re_check(
        self, db_session, mission_user, mission_badges,
    ):
        from app.achievements.streak_service import process_streak_on_activity

        today = date.today()
        # Pre-existing completion marker for today
        db_session.add(StreakEvent(
            user_id=mission_user.id,
            event_type='mission_selected',
            coins_delta=0,
            event_date=today,
            details={'mission_type': 'progress'},
        ))
        db_session.add(StreakEvent(
            user_id=mission_user.id,
            event_type='plan_completed',
            coins_delta=0,
            event_date=today,
            details={'plans_completed_total': 1, 'rank_code': 'novice'},
        ))
        db_session.flush()

        with patch(
            'app.achievements.services.AchievementService.check_mission_achievements'
        ) as mock_check, \
             patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.achievements.streak_service.get_streak_status', return_value={
                 'streak': 1, 'coins_balance': 0, 'has_activity_today': True,
                 'can_repair': False, 'missed_date': None, 'repair_cost': None,
                 'required_steps': 1, 'steps_total': 4,
             }), \
             patch('app.achievements.streak_service.find_missed_date', return_value=None), \
             patch('app.achievements.streak_service.check_streak_milestone',
                   return_value=None):
            process_streak_on_activity(
                mission_user.id, steps_done=4, steps_total=4, tz='UTC',
            )

        mock_check.assert_not_called()

    def test_partial_plan_does_not_trigger_mission_check(
        self, db_session, mission_user, mission_badges,
    ):
        from app.achievements.streak_service import process_streak_on_activity

        today = date.today()
        db_session.add(StreakEvent(
            user_id=mission_user.id,
            event_type='mission_selected',
            coins_delta=0,
            event_date=today,
            details={'mission_type': 'progress'},
        ))
        db_session.flush()

        with patch(
            'app.achievements.services.AchievementService.check_mission_achievements'
        ) as mock_check, \
             patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.achievements.streak_service.get_streak_status', return_value={
                 'streak': 1, 'coins_balance': 0, 'has_activity_today': True,
                 'can_repair': False, 'missed_date': None, 'repair_cost': None,
                 'required_steps': 1, 'steps_total': 4,
             }), \
             patch('app.achievements.streak_service.find_missed_date', return_value=None), \
             patch('app.achievements.streak_service.check_streak_milestone',
                   return_value=None):
            process_streak_on_activity(
                mission_user.id, steps_done=2, steps_total=4, tz='UTC',
            )

        mock_check.assert_not_called()

    def test_missing_mission_selected_event_skips_check(
        self, db_session, mission_user, mission_badges,
    ):
        """If no mission type was recorded for today, badge check is skipped gracefully."""
        from app.achievements.streak_service import process_streak_on_activity

        with patch(
            'app.achievements.services.AchievementService.check_mission_achievements'
        ) as mock_check, \
             patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.achievements.streak_service.get_streak_status', return_value={
                 'streak': 1, 'coins_balance': 0, 'has_activity_today': True,
                 'can_repair': False, 'missed_date': None, 'repair_cost': None,
                 'required_steps': 1, 'steps_total': 4,
             }), \
             patch('app.achievements.streak_service.find_missed_date', return_value=None), \
             patch('app.achievements.streak_service.check_streak_milestone',
                   return_value=None):
            process_streak_on_activity(
                mission_user.id, steps_done=4, steps_total=4, tz='UTC',
            )

        mock_check.assert_not_called()
