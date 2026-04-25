"""Unit tests for app.achievements.xp_service."""
import pytest
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from app.achievements.xp_service import (
    LINEAR_XP,
    PHASE_XP,
    PERFECT_DAY_BONUS_XP,
    PERFECT_DAY_BONUS_XP_LINEAR,
    FIRST_OF_DAY_BONUS_XP,
    STREAK_MULTIPLIER_MAX,
    PERFECT_DAY_MULTIPLIERS,
    LevelInfo,
    XPAward,
    apply_score_to_base,
    award_linear_xp,
    award_xp,
    award_phase_xp_idempotent,
    award_perfect_day_xp_idempotent,
    get_level_info,
    get_linear_xp_amount,
    get_streak_multiplier,
    get_perfect_day_multiplier,
    get_perfect_day_info,
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

    def test_score_none_is_full_base(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.current_streak_days = 0
        stats.total_xp = 0
        result = award_xp(test_user.id, 100, 'graded_none', score=None)
        assert result.xp_awarded == 100

    def test_score_100_is_full_base(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.current_streak_days = 0
        stats.total_xp = 0
        result = award_xp(test_user.id, 100, 'graded_perfect', score=100)
        assert result.xp_awarded == 100

    def test_score_0_is_half_base(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.current_streak_days = 0
        stats.total_xp = 0
        result = award_xp(test_user.id, 100, 'graded_zero', score=0)
        assert result.xp_awarded == 50

    def test_score_70_scales_to_85_percent(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.current_streak_days = 0
        stats.total_xp = 0
        # 100 * (0.5 + 70/200) = 100 * 0.85 = 85
        result = award_xp(test_user.id, 100, 'graded_70', score=70)
        assert result.xp_awarded == 85

    def test_score_clamped_above_100(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.current_streak_days = 0
        stats.total_xp = 0
        result = award_xp(test_user.id, 100, 'graded_above', score=150)
        assert result.xp_awarded == 100

    def test_score_clamped_below_0(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.current_streak_days = 0
        stats.total_xp = 0
        result = award_xp(test_user.id, 100, 'graded_neg', score=-50)
        assert result.xp_awarded == 50

    def test_score_with_streak_multiplier(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
            db.session.flush()
        stats.current_streak_days = 50  # 2.0x
        stats.total_xp = 0
        # base 100, score=50 → 75; * 2.0 streak = 150
        result = award_xp(test_user.id, 100, 'graded_streak', score=50)
        assert result.multiplier == 2.0
        assert result.xp_awarded == 150

    def test_apply_score_to_base_helper(self):
        assert apply_score_to_base(100, None) == 100
        assert apply_score_to_base(100, 0) == 50
        assert apply_score_to_base(100, 100) == 100
        assert apply_score_to_base(100, 70) == 85
        assert apply_score_to_base(20, 100) == 20
        assert apply_score_to_base(20, 0) == 10

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
            {'id': 'phase_recall', 'phase': 'recall', 'mode': 'srs_review', 'required': True},
            {'id': 'phase_learn', 'phase': 'learn', 'mode': 'curriculum_lesson', 'required': True},
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
        awarded = {event.details['phase_id']: event.details['xp'] for event in xp_events}
        assert awarded['phase_recall'] == PHASE_XP['recall']
        assert awarded['phase_learn'] == PHASE_XP['learn']

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

    def test_bonus_phase_awards_xp_once_completed(self, db_session, test_user):
        from app.achievements.streak_service import process_streak_on_activity
        from app.achievements.models import StreakEvent
        self._ensure_stats(db_session, test_user.id)
        phases = [
            {'id': 'phase_learn', 'phase': 'learn', 'mode': 'curriculum_lesson', 'required': True},
            {'id': 'phase_bonus', 'phase': 'bonus', 'mode': 'fun_fact_quiz', 'required': False},
        ]
        plan_completion = {'phase_learn': True, 'phase_bonus': True}
        daily_plan = {'phases': phases}

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.telegram.queries.get_current_streak', return_value=0):
            process_streak_on_activity(
                test_user.id, 1, 1,
                daily_plan=daily_plan, plan_completion=plan_completion,
            )

        xp_events = StreakEvent.query.filter_by(
            user_id=test_user.id, event_type='xp_phase'
        ).all()
        awarded = {event.details['phase_id']: event.details['xp'] for event in xp_events}
        assert awarded['phase_learn'] == PHASE_XP['learn']
        assert awarded['phase_bonus'] == PHASE_XP['fun_fact_quiz']

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


# ---------------------------------------------------------------------------
# get_perfect_day_multiplier
# ---------------------------------------------------------------------------

class TestGetPerfectDayMultiplier:
    def test_zero_or_none_returns_1x(self):
        assert get_perfect_day_multiplier(0) == 1.0
        assert get_perfect_day_multiplier(None) == 1.0
        assert get_perfect_day_multiplier(-1) == 1.0

    def test_day_1_returns_1x(self):
        assert get_perfect_day_multiplier(1) == 1.0

    def test_day_2_returns_1_2x(self):
        assert get_perfect_day_multiplier(2) == 1.2

    def test_day_3_returns_1_5x(self):
        assert get_perfect_day_multiplier(3) == 1.5

    def test_day_4_returns_1_5x(self):
        # 4 is >= 3 but < 5, so still 1.5x
        assert get_perfect_day_multiplier(4) == 1.5

    def test_day_5_returns_2x(self):
        assert get_perfect_day_multiplier(5) == 2.0

    def test_day_6_returns_2x(self):
        assert get_perfect_day_multiplier(6) == 2.0

    def test_day_7_returns_2_5x(self):
        assert get_perfect_day_multiplier(7) == 2.5

    def test_day_100_returns_2_5x(self):
        assert get_perfect_day_multiplier(100) == 2.5

    def test_multiplier_is_non_decreasing(self):
        prev = get_perfect_day_multiplier(0)
        for d in range(1, 20):
            curr = get_perfect_day_multiplier(d)
            assert curr >= prev
            prev = curr


# ---------------------------------------------------------------------------
# get_perfect_day_info
# ---------------------------------------------------------------------------

class TestGetPerfectDayInfo:
    def test_returns_zero_for_new_user(self, db_session, test_user):
        info = get_perfect_day_info(test_user.id)
        assert info['consecutive_days'] == 0
        assert info['current_multiplier'] == 1.0

    def test_reflects_consecutive_days_from_stats(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
        stats.consecutive_perfect_days = 3
        db.session.flush()

        info = get_perfect_day_info(test_user.id)
        assert info['consecutive_days'] == 3
        assert info['current_multiplier'] == 1.5

    def test_message_includes_streak_count(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
        stats.consecutive_perfect_days = 5
        db.session.flush()

        info = get_perfect_day_info(test_user.id)
        assert '5' in info['message']

    def test_next_multiplier_greater_when_milestone_ahead(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
        stats.consecutive_perfect_days = 1
        db.session.flush()

        info = get_perfect_day_info(test_user.id)
        assert info['next_multiplier'] > info['current_multiplier']

    def test_stale_stats_reset_when_last_perfect_day_is_old(self, db_session, test_user):
        from app.achievements.models import StreakEvent, UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=test_user.id)
            db.session.add(stats)
        stats.consecutive_perfect_days = 6
        db.session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=date.today() - timedelta(days=3),
            coins_delta=0,
            details={'xp': 50, 'consecutive_days': 6, 'perfect_day_multiplier': 2.0},
        ))
        db.session.flush()

        info = get_perfect_day_info(test_user.id)
        assert info['consecutive_days'] == 0
        assert info['current_multiplier'] == 1.0


# ---------------------------------------------------------------------------
# award_perfect_day_xp_idempotent - consecutive tracking
# ---------------------------------------------------------------------------

class TestAwardPerfectDayConsecutive:
    def _ensure_stats(self, db_session, user_id):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if stats is None:
            stats = UserStatistics(user_id=user_id, total_xp=0, current_streak_days=0)
            db.session.add(stats)
            db.session.flush()
        return stats

    def test_first_perfect_day_sets_consecutive_to_1(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        award_perfect_day_xp_idempotent(test_user.id, today)
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.consecutive_perfect_days == 1

    def test_consecutive_day_increments_counter(self, db_session, test_user):
        from app.achievements.models import UserStatistics, StreakEvent
        from app.utils.db import db
        from datetime import timedelta
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Seed yesterday's perfect day event
        db.session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=yesterday,
            coins_delta=0,
            details={'xp': 50, 'consecutive_days': 1, 'perfect_day_multiplier': 1.0},
        ))
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        stats.consecutive_perfect_days = 1
        db.session.flush()

        award_perfect_day_xp_idempotent(test_user.id, today)
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.consecutive_perfect_days == 2

    def test_missing_day_resets_counter_to_1(self, db_session, test_user):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = self._ensure_stats(db_session, test_user.id)
        stats.consecutive_perfect_days = 4  # had 4 days before a gap
        db.session.flush()

        # Award today with no yesterday event (gap)
        today = date.today()
        award_perfect_day_xp_idempotent(test_user.id, today)
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.consecutive_perfect_days == 1

    def test_consecutive_bonus_increases_xp(self, db_session, test_user):
        from app.achievements.models import UserStatistics, StreakEvent
        from app.utils.db import db
        from datetime import timedelta
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        yesterday = today - timedelta(days=1)
        two_days_ago = today - timedelta(days=2)

        # Seed 2 consecutive prior days so today becomes day 3 (1.5x)
        for d in (two_days_ago, yesterday):
            db.session.add(StreakEvent(
                user_id=test_user.id,
                event_type='xp_perfect_day',
                event_date=d,
                coins_delta=0,
                details={'xp': 50, 'consecutive_days': 1, 'perfect_day_multiplier': 1.0},
            ))
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        stats.consecutive_perfect_days = 2
        stats.current_streak_days = 0
        db.session.flush()

        result = award_perfect_day_xp_idempotent(test_user.id, today)
        assert result is not None
        # Day 3 = 1.5x perfect multiplier, streak=0 so streak mult=1.0
        # Base = 50 * 1.5 = 75, streak mult = 1.0 → awarded = 75
        assert result.xp_awarded == int(PERFECT_DAY_BONUS_XP * 1.5)

    def test_day_7_applies_2_5x_multiplier(self, db_session, test_user):
        from app.achievements.models import UserStatistics, StreakEvent
        from app.utils.db import db
        from datetime import timedelta
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        yesterday = today - timedelta(days=1)

        # Seed yesterday to make today day 7
        db.session.add(StreakEvent(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=yesterday,
            coins_delta=0,
            details={'xp': 50, 'consecutive_days': 6, 'perfect_day_multiplier': 2.0},
        ))
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        stats.consecutive_perfect_days = 6
        stats.current_streak_days = 0
        db.session.flush()

        result = award_perfect_day_xp_idempotent(test_user.id, today)
        assert result is not None
        assert result.xp_awarded == int(PERFECT_DAY_BONUS_XP * 2.5)

    def test_event_stores_consecutive_days(self, db_session, test_user):
        from app.achievements.models import StreakEvent
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        award_perfect_day_xp_idempotent(test_user.id, today)
        event = StreakEvent.query.filter_by(
            user_id=test_user.id,
            event_type='xp_perfect_day',
            event_date=today,
        ).first()
        assert event is not None
        assert event.details.get('consecutive_days') == 1
        assert event.details.get('perfect_day_multiplier') == 1.0


# ---------------------------------------------------------------------------
# process_streak_on_activity returns perfect_day_info
# ---------------------------------------------------------------------------

class TestProcessStreakPerfectDayInfo:
    def _ensure_stats(self, db_session, user_id):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if stats is None:
            stats = UserStatistics(user_id=user_id, total_xp=0, current_streak_days=0)
            db.session.add(stats)
            db.session.flush()
        return stats

    def test_perfect_day_info_in_result_when_all_done(self, db_session, test_user):
        from app.achievements.streak_service import process_streak_on_activity
        self._ensure_stats(db_session, test_user.id)
        phases = [
            {'id': 'p1', 'mode': 'learn', 'required': True},
            {'id': 'p2', 'mode': 'recall', 'required': True},
        ]
        plan_completion = {'p1': True, 'p2': True}
        daily_plan = {'phases': phases}

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.telegram.queries.get_current_streak', return_value=1):
            result = process_streak_on_activity(
                test_user.id, 2, 2,
                daily_plan=daily_plan, plan_completion=plan_completion,
            )

        assert 'perfect_day_info' in result
        assert result['perfect_day_info'] is not None
        assert result['perfect_day_info']['consecutive_days'] >= 1

    def test_perfect_day_info_none_when_no_phases(self, db_session, test_user):
        from app.achievements.streak_service import process_streak_on_activity
        self._ensure_stats(db_session, test_user.id)

        with patch('app.telegram.queries.has_activity_today', return_value=True), \
             patch('app.telegram.queries.get_current_streak', return_value=1):
            result = process_streak_on_activity(test_user.id, 1, 2)

        # No phases in daily_plan → perfect_day_info should be None
        assert result.get('perfect_day_info') is None


# ---------------------------------------------------------------------------
# Linear daily plan XP
# ---------------------------------------------------------------------------

class TestLinearXpMap:
    def test_all_values_positive(self):
        for source, xp in LINEAR_XP.items():
            assert xp > 0, f"LINEAR_XP[{source!r}] must be positive"

    def test_known_sources_present(self):
        expected = {
            'linear_curriculum_card': 20,
            'linear_curriculum_vocabulary': 18,
            'linear_curriculum_grammar': 18,
            'linear_curriculum_quiz': 12,
            'linear_curriculum_listening_quiz': 12,
            'linear_curriculum_dialogue_completion_quiz': 12,
            'linear_curriculum_ordering_quiz': 12,
            'linear_curriculum_translation_quiz': 12,
            'linear_curriculum_final_test': 12,
            'linear_curriculum_reading': 15,
            'linear_curriculum_listening_immersion': 15,
            'linear_srs_global': 8,
            'linear_book_reading': 15,
            'linear_error_review': 10,
        }
        for source, xp in expected.items():
            assert LINEAR_XP.get(source) == xp, f"LINEAR_XP[{source!r}] != {xp}"

    def test_linear_perfect_day_bonus_is_25(self):
        assert PERFECT_DAY_BONUS_XP_LINEAR == 25

    def test_mission_perfect_day_bonus_unchanged(self):
        assert PERFECT_DAY_BONUS_XP == 50

    def test_get_linear_xp_amount_returns_value(self):
        assert get_linear_xp_amount('linear_curriculum_card') == 20
        assert get_linear_xp_amount('linear_srs_global') == 8

    def test_get_linear_xp_amount_raises_on_unknown(self):
        with pytest.raises(KeyError):
            get_linear_xp_amount('linear_does_not_exist')


class TestAwardLinearXp:
    def _ensure_stats(self, db_session, user_id):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if stats is None:
            stats = UserStatistics(user_id=user_id, total_xp=0, current_streak_days=0)
            db.session.add(stats)
            db.session.flush()
        return stats

    def test_awards_card_xp_without_streak(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        result = award_linear_xp(test_user.id, 'linear_curriculum_card')
        assert result.xp_awarded == 20
        assert result.multiplier == 1.0

    def test_awards_srs_xp_without_streak(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        result = award_linear_xp(test_user.id, 'linear_srs_global')
        assert result.xp_awarded == 8

    def test_awards_book_reading_xp_without_streak(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        result = award_linear_xp(test_user.id, 'linear_book_reading')
        assert result.xp_awarded == 15

    def test_awards_error_review_xp_without_streak(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        result = award_linear_xp(test_user.id, 'linear_error_review')
        assert result.xp_awarded == 10

    def test_awards_quiz_xp_for_all_quiz_types(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        quiz_sources = [
            'linear_curriculum_quiz',
            'linear_curriculum_listening_quiz',
            'linear_curriculum_dialogue_completion_quiz',
            'linear_curriculum_ordering_quiz',
            'linear_curriculum_translation_quiz',
            'linear_curriculum_final_test',
        ]
        for source in quiz_sources:
            result = award_linear_xp(test_user.id, source)
            assert result.xp_awarded == 12, f"{source} should award 12 base XP"

    def test_streak_multiplier_applied(self, db_session, test_user):
        from app.utils.db import db
        stats = self._ensure_stats(db_session, test_user.id)
        stats.current_streak_days = 50  # multiplier = 2.0
        db.session.flush()
        result = award_linear_xp(test_user.id, 'linear_curriculum_card')
        assert result.multiplier == 2.0
        assert result.xp_awarded == 40  # 20 * 2.0

    def test_unknown_source_raises(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        with pytest.raises(KeyError):
            award_linear_xp(test_user.id, 'linear_bogus_source')

    def test_score_scales_linear_xp(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        # quiz base = 12, score=100 → 12; score=0 → 6; score=50 → 9
        r_full = award_linear_xp(
            test_user.id, 'linear_curriculum_quiz', score=100,
        )
        assert r_full.xp_awarded == 12
        r_half = award_linear_xp(
            test_user.id, 'linear_curriculum_quiz', score=0,
        )
        assert r_half.xp_awarded == 6
        r_mid = award_linear_xp(
            test_user.id, 'linear_curriculum_quiz', score=50,
        )
        assert r_mid.xp_awarded == 9

    def test_score_none_unchanged_for_linear(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        result = award_linear_xp(test_user.id, 'linear_curriculum_quiz', score=None)
        assert result.xp_awarded == 12

    def test_baseline_day_without_streak_is_43_xp(self, db_session, test_user):
        """Baseline linear day (card + srs + book) without streak = 43 XP."""
        from app.achievements.models import UserStatistics
        self._ensure_stats(db_session, test_user.id)
        award_linear_xp(test_user.id, 'linear_curriculum_card')      # 20
        award_linear_xp(test_user.id, 'linear_srs_global')           # 8
        award_linear_xp(test_user.id, 'linear_book_reading')         # 15
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.total_xp == 43

    def test_first_level_reached_in_about_2_5_baseline_days(self, db_session, test_user):
        """Level 1 → Level 2 threshold (100 XP) reached within 3 baseline days."""
        from app.achievements.models import UserStatistics
        self._ensure_stats(db_session, test_user.id)
        # 2 baseline days = 86 XP (still level 1)
        for _ in range(2):
            award_linear_xp(test_user.id, 'linear_curriculum_card')
            award_linear_xp(test_user.id, 'linear_srs_global')
            award_linear_xp(test_user.id, 'linear_book_reading')
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.total_xp == 86
        assert stats.current_level == 1

        # 3rd partial day: +20 card pushes to 106 → level 2
        award_linear_xp(test_user.id, 'linear_curriculum_card')
        stats = UserStatistics.query.filter_by(user_id=test_user.id).first()
        assert stats.total_xp == 106
        assert stats.current_level == 2


class TestLinearPerfectDayBonus:
    def _ensure_stats(self, db_session, user_id):
        from app.achievements.models import UserStatistics
        from app.utils.db import db
        stats = UserStatistics.query.filter_by(user_id=user_id).first()
        if stats is None:
            stats = UserStatistics(user_id=user_id, total_xp=0, current_streak_days=0)
            db.session.add(stats)
            db.session.flush()
        return stats

    def test_linear_bonus_awards_25(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        result = award_perfect_day_xp_idempotent(test_user.id, today, is_linear=True)
        assert result is not None
        assert result.xp_awarded == PERFECT_DAY_BONUS_XP_LINEAR  # 25, no streak

    def test_mission_bonus_still_50(self, db_session, test_user):
        self._ensure_stats(db_session, test_user.id)
        today = date.today()
        result = award_perfect_day_xp_idempotent(test_user.id, today)
        assert result is not None
        assert result.xp_awarded == PERFECT_DAY_BONUS_XP  # 50, no streak

    def test_linear_bonus_applies_streak_multiplier(self, db_session, test_user):
        from app.utils.db import db
        stats = self._ensure_stats(db_session, test_user.id)
        stats.current_streak_days = 50  # 2.0x streak
        db.session.flush()
        result = award_perfect_day_xp_idempotent(
            test_user.id, date.today(), is_linear=True
        )
        assert result is not None
        assert result.multiplier == 2.0
        assert result.xp_awarded == PERFECT_DAY_BONUS_XP_LINEAR * 2  # 50
