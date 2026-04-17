"""Unit tests for app.achievements.xp_service."""
import pytest
from datetime import date
from unittest.mock import patch, MagicMock

from app.achievements.xp_service import (
    PHASE_XP,
    PERFECT_DAY_BONUS_XP,
    FIRST_OF_DAY_BONUS_XP,
    STREAK_MULTIPLIER_MAX,
    LevelInfo,
    XPAward,
    award_xp,
    award_phase_xp_idempotent,
    award_perfect_day_xp_idempotent,
    get_level_info,
    get_streak_multiplier,
    xp_for_level,
)


# ---------------------------------------------------------------------------
# xp_for_level
# ---------------------------------------------------------------------------

class TestXpForLevel:
    def test_level_1_is_zero(self):
        assert xp_for_level(1) == 0

    def test_level_2_is_100(self):
        assert xp_for_level(2) == 100

    def test_level_3_is_300(self):
        assert xp_for_level(3) == 300  # 100 + 200

    def test_level_4_is_600(self):
        assert xp_for_level(4) == 600  # 100 + 200 + 300

    def test_level_5_is_1000(self):
        assert xp_for_level(5) == 1000  # 100+200+300+400

    def test_level_0_returns_0(self):
        assert xp_for_level(0) == 0

    def test_strictly_increasing(self):
        thresholds = [xp_for_level(n) for n in range(1, 20)]
        for prev, nxt in zip(thresholds, thresholds[1:]):
            assert nxt > prev


# ---------------------------------------------------------------------------
# get_streak_multiplier
# ---------------------------------------------------------------------------

class TestGetStreakMultiplier:
    def test_zero_streak_is_1_0(self):
        assert get_streak_multiplier(0) == 1.0

    def test_multiplier_increases_with_streak(self):
        m10 = get_streak_multiplier(10)
        m20 = get_streak_multiplier(20)
        assert m20 > m10 > 1.0

    def test_capped_at_max(self):
        assert get_streak_multiplier(1000) == STREAK_MULTIPLIER_MAX

    def test_negative_streak_treated_as_zero(self):
        assert get_streak_multiplier(-5) == 1.0

    def test_none_streak_treated_as_zero(self):
        assert get_streak_multiplier(None) == 1.0

    def test_50_streak_is_2_0(self):
        # 1.0 + 50*0.02 = 2.0 exactly
        assert get_streak_multiplier(50) == 2.0

    def test_51_streak_still_capped(self):
        assert get_streak_multiplier(51) == 2.0


# ---------------------------------------------------------------------------
# get_level_info
# ---------------------------------------------------------------------------

class TestGetLevelInfo:
    def test_zero_xp_is_level_1(self):
        info = get_level_info(0)
        assert info.current_level == 1
        assert info.xp_in_level == 0
        assert info.xp_to_next == 100

    def test_exactly_at_level_2_threshold(self):
        info = get_level_info(100)
        assert info.current_level == 2
        assert info.xp_in_level == 0
        assert info.xp_to_next == 200

    def test_just_below_level_2(self):
        info = get_level_info(99)
        assert info.current_level == 1
        assert info.xp_to_next == 1

    def test_just_above_level_2(self):
        info = get_level_info(101)
        assert info.current_level == 2
        assert info.xp_in_level == 1

    def test_exactly_at_level_3(self):
        info = get_level_info(300)
        assert info.current_level == 3
        assert info.xp_in_level == 0

    def test_midway_through_level_2(self):
        # Level 2 spans 100-299 (200 XP wide); 200 XP = midpoint
        info = get_level_info(200)
        assert info.current_level == 2
        assert info.progress_percent == 50.0

    def test_progress_percent_range(self):
        for xp in range(0, 2000, 50):
            info = get_level_info(xp)
            assert 0.0 <= info.progress_percent <= 100.0

    def test_negative_xp_treated_as_zero(self):
        info = get_level_info(-10)
        assert info.current_level == 1

    def test_none_xp_treated_as_zero(self):
        info = get_level_info(None)
        assert info.current_level == 1

    def test_high_xp_returns_high_level(self):
        # Level 10: 100*9*10/2 = 4500 XP
        info = get_level_info(4500)
        assert info.current_level == 10

    def test_returns_level_info_instance(self):
        assert isinstance(get_level_info(0), LevelInfo)


# ---------------------------------------------------------------------------
# award_xp - uses DB; requires app context and db_session
# ---------------------------------------------------------------------------

class TestAwardXp:
    def test_awards_xp_and_returns_xp_award(self, db_session, test_user):
        result = award_xp(test_user.id, 100, 'test')
        assert isinstance(result, XPAward)
        assert result.xp_awarded >= 100

    def test_streak_multiplier_applied(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            from app.utils.db import db
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.current_streak_days = 50  # multiplier should be 2.0

        result = award_xp(test_user.id, 100, 'test_50_streak')
        assert result.multiplier == 2.0
        assert result.xp_awarded == 200

    def test_no_streak_multiplier_is_1x(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.current_streak_days = 0

        result = award_xp(test_user.id, 50, 'no_streak')
        assert result.multiplier == 1.0
        assert result.xp_awarded == 50

    def test_level_up_detected(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.total_xp = 95
        stats.current_level = 1
        stats.current_streak_days = 0

        result = award_xp(test_user.id, 10, 'level_up_test')
        assert result.leveled_up is True
        assert result.new_level == 2

    def test_no_level_up_when_not_crossing_threshold(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.total_xp = 0
        stats.current_level = 1
        stats.current_streak_days = 0

        result = award_xp(test_user.id, 10, 'no_level_up_test')
        assert result.leveled_up is False
        assert result.new_level == 1

    def test_updates_user_statistics(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.total_xp = 0
        stats.current_streak_days = 0

        award_xp(test_user.id, 200, 'update_test')
        updated = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert updated.total_xp == 200
        assert updated.current_level == 2

    def test_invalid_amount_raises(self, db_session, test_user):
        with pytest.raises(ValueError):
            award_xp(test_user.id, 0, 'zero')
        with pytest.raises(ValueError):
            award_xp(test_user.id, -10, 'negative')

    def test_phase_xp_constants_all_positive(self):
        for phase, xp in PHASE_XP.items():
            assert xp > 0, f"PHASE_XP[{phase!r}] must be positive"

    def test_perfect_day_bonus_positive(self):
        assert PERFECT_DAY_BONUS_XP > 0

    def test_first_of_day_bonus_positive(self):
        assert FIRST_OF_DAY_BONUS_XP > 0


# ---------------------------------------------------------------------------
# award_phase_xp_idempotent
# ---------------------------------------------------------------------------

class TestAwardPhaseXpIdempotent:
    def _ensure_stats(self, db_session, user_id):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if stats is None:
            stats = UserStatistics(user_id=user_id, total_xp=0, current_streak_days=0)
            db.session.add(stats)
            db.session.flush()
        return stats

    def test_awards_xp_for_phase(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        result = award_phase_xp_idempotent(test_user.id, 'phase_1', 'learn', today)
        assert result is not None
        assert result.xp_awarded >= PHASE_XP['learn']

    def test_uses_phase_xp_map(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        for mode, expected_base in PHASE_XP.items():
            phase_id = f'phase_{mode}'
            result = award_phase_xp_idempotent(test_user.id, phase_id, mode, today)
            assert result is not None
            assert result.xp_awarded >= expected_base

    def test_idempotent_returns_none_on_second_call(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        first = award_phase_xp_idempotent(test_user.id, 'phase_dup', 'recall', today)
        assert first is not None
        second = award_phase_xp_idempotent(test_user.id, 'phase_dup', 'recall', today)
        assert second is None

    def test_different_phases_both_awarded(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        r1 = award_phase_xp_idempotent(test_user.id, 'phase_a', 'recall', today)
        r2 = award_phase_xp_idempotent(test_user.id, 'phase_b', 'learn', today)
        assert r1 is not None
        assert r2 is not None

    def test_applies_streak_multiplier(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = self._ensure_stats(db_session, test_user.id)
        stats.current_streak_days = 50  # 2x multiplier
        db.session.flush()
        today = date.today()
        result = award_phase_xp_idempotent(test_user.id, 'phase_mult', 'learn', today)
        assert result is not None
        assert result.multiplier == 2.0
        assert result.xp_awarded == PHASE_XP['learn'] * 2

    def test_unknown_mode_falls_back_to_check(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        result = award_phase_xp_idempotent(test_user.id, 'phase_unk', 'unknown_mode', today)
        assert result is not None
        assert result.xp_awarded >= PHASE_XP['check']

    def test_level_up_detected(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = self._ensure_stats(db_session, test_user.id)
        stats.total_xp = 90
        stats.current_level = 1
        stats.current_streak_days = 0
        db.session.flush()
        today = date.today()
        result = award_phase_xp_idempotent(test_user.id, 'phase_lvlup', 'learn', today)
        assert result is not None
        assert result.leveled_up is True
        assert result.new_level == 2


# ---------------------------------------------------------------------------
# award_perfect_day_xp_idempotent
# ---------------------------------------------------------------------------

class TestAwardPerfectDayXpIdempotent:
    def _ensure_stats(self, db_session, user_id):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if stats is None:
            stats = UserStatistics(user_id=user_id, total_xp=0, current_streak_days=0)
            db.session.add(stats)
            db.session.flush()
        return stats

    def test_awards_perfect_day_bonus(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        result = award_perfect_day_xp_idempotent(test_user.id, today)
        assert result is not None
        assert result.xp_awarded >= PERFECT_DAY_BONUS_XP

    def test_idempotent_second_call_returns_none(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        first = award_perfect_day_xp_idempotent(test_user.id, today)
        assert first is not None
        second = award_perfect_day_xp_idempotent(test_user.id, today)
        assert second is None

    def test_different_days_both_awarded(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        from datetime import timedelta
        today = date.today()
        yesterday = today - timedelta(days=1)
        r1 = award_perfect_day_xp_idempotent(test_user.id, today)
        r2 = award_perfect_day_xp_idempotent(test_user.id, yesterday)
        assert r1 is not None
        assert r2 is not None

    def test_applies_streak_multiplier(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = self._ensure_stats(db_session, test_user.id)
        stats.current_streak_days = 50
        db.session.flush()
        today = date.today()
        result = award_perfect_day_xp_idempotent(test_user.id, today)
        assert result is not None
        assert result.multiplier == 2.0
        assert result.xp_awarded == PERFECT_DAY_BONUS_XP * 2


# ---------------------------------------------------------------------------
# Integration: process_streak_on_activity awards XP
# ---------------------------------------------------------------------------

class TestProcessStreakActivityXp:
    def _make_phases(self):
        return [
            {'id': 'phase_recall', 'mode': 'words', 'required': True},
            {'id': 'phase_learn', 'mode': 'lesson', 'required': True},
        ]

    def _ensure_stats(self, db_session, user_id):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if stats is None:
            stats = UserStatistics(user_id=user_id, total_xp=0, current_streak_days=0)
            db.session.add(stats)
            db.session.flush()
        return stats

    def test_xp_awarded_for_completed_phases(self, db_session, test_user):
        from app.achievements.streak_service import process_streak_on_activity
        from app.achievements.models import UserStatistics, StreakEvent
        from app.utils.db import db
        self._ensure_stats(db_session, test_user.id)
        phases = self._make_phases()
        plan_completion = {'phase_recall': True, 'phase_learn': True}
        daily_plan = {'phases': phases}

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.telegram.queries.get_current_streak', return_value=3):
            process_streak_on_activity(
                test_user.id, 2, 2,
                daily_plan=daily_plan,
                plan_completion=plan_completion,
            )

        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.total_xp > 0
        xp_events = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type='xp_phase'
        ).all()
        assert len(xp_events) == 2

    def test_perfect_day_bonus_awarded_when_all_done(self, db_session, test_user):
        from app.achievements.streak_service import process_streak_on_activity
        from app.achievements.models import UserStatistics, StreakEvent
        self._ensure_stats(db_session, test_user.id)
        phases = self._make_phases()
        plan_completion = {'phase_recall': True, 'phase_learn': True}
        daily_plan = {'phases': phases}

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.telegram.queries.get_current_streak', return_value=1):
            process_streak_on_activity(
                test_user.id, 2, 2,
                daily_plan=daily_plan,
                plan_completion=plan_completion,
            )

        perfect_event = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type='xp_perfect_day'
        ).first()
        assert perfect_event is not None

    def test_perfect_day_bonus_not_awarded_when_partial(self, db_session, test_user):
        from app.achievements.streak_service import process_streak_on_activity
        from app.achievements.models import UserStatistics, StreakEvent
        self._ensure_stats(db_session, test_user.id)
        phases = self._make_phases()
        plan_completion = {'phase_recall': True, 'phase_learn': False}
        daily_plan = {'phases': phases}

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.telegram.queries.get_current_streak', return_value=1):
            process_streak_on_activity(
                test_user.id, 1, 2,
                daily_plan=daily_plan,
                plan_completion=plan_completion,
            )

        perfect_event = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type='xp_perfect_day'
        ).first()
        assert perfect_event is None

    def test_xp_not_awarded_twice_on_repeat_call(self, db_session, test_user):
        from app.achievements.streak_service import process_streak_on_activity
        from app.achievements.models import UserStatistics, StreakEvent
        self._ensure_stats(db_session, test_user.id)
        phases = self._make_phases()
        plan_completion = {'phase_recall': True, 'phase_learn': True}
        daily_plan = {'phases': phases}

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.telegram.queries.get_current_streak', return_value=1):
            process_streak_on_activity(
                test_user.id, 2, 2,
                daily_plan=daily_plan, plan_completion=plan_completion,
            )
            process_streak_on_activity(
                test_user.id, 2, 2,
                daily_plan=daily_plan, plan_completion=plan_completion,
            )

        xp_events = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type='xp_phase'
        ).all()
        assert len(xp_events) == 2

    def test_level_up_notification_sent(self, db_session, test_user):
        from app.achievements.streak_service import process_streak_on_activity
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = self._ensure_stats(db_session, test_user.id)
        stats.total_xp = 90
        stats.current_level = 1
        stats.current_streak_days = 0
        db.session.flush()

        phases = [{'id': 'phase_big', 'mode': 'learn', 'required': True}]
        plan_completion = {'phase_big': True}
        daily_plan = {'phases': phases}

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.telegram.queries.get_current_streak', return_value=0), \
             patch('app.notifications.services.notify_level_up') as mock_notify:
            result = process_streak_on_activity(
                test_user.id, 1, 1,
                daily_plan=daily_plan, plan_completion=plan_completion,
            )

        assert result.get('xp_level_up') is not None
        assert result['xp_level_up']['new_level'] == 2
        mock_notify.assert_called_once_with(test_user.id, 2)
