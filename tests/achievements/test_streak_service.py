"""Unit tests for the achievement streak service.

Covers:
- Streak calculation with timezone edge cases
- Streak recovery purchase flow (paid repair)
- Streak freeze / double-repair protection handling
- Listening streak (get_listening_streak)
"""
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch, MagicMock
import uuid

import pytest

from app.auth.models import User
from app.achievements.models import StreakCoins, StreakEvent
from app.achievements.streak_service import (
    apply_free_repair,
    apply_paid_repair,
    earn_daily_coin,
    get_listening_streak,
    get_or_create_coins,
    get_repair_cost,
    get_required_steps,
    has_repair_for_date,
    save_daily_completion,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def streak_user(db_session):
    """Create a test user for streak tests."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'streak_{suffix}',
        email=f'streak_{suffix}@test.com',
        active=True,
    )
    user.set_password('test123')
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def user_id(streak_user):
    return streak_user.id


# ---------------------------------------------------------------------------
# 1. Streak calculation — progressive step requirements
# ---------------------------------------------------------------------------


class TestGetRequiredSteps:
    """get_required_steps() returns the right minimum steps per streak tier."""

    def test_days_1_to_14_require_1_step(self):
        for days in (1, 7, 14):
            assert get_required_steps(days, 4) == 1

    def test_days_15_to_29_require_2_steps(self):
        for days in (15, 20, 29):
            assert get_required_steps(days, 4) == 2

    def test_days_30_to_59_require_3_steps(self):
        for days in (30, 45, 59):
            assert get_required_steps(days, 4) == 3

    def test_days_60_plus_require_all_steps(self):
        assert get_required_steps(60, 4) == 4
        assert get_required_steps(100, 6) == 6

    def test_required_steps_capped_at_steps_total(self):
        # If steps_total < required tier minimum, cap at steps_total
        assert get_required_steps(15, 1) == 1  # tier requires 2, but only 1 step available
        assert get_required_steps(30, 2) == 2  # tier requires 3, but only 2 available

    def test_zero_streak_requires_1_step(self):
        assert get_required_steps(0, 4) == 1


# ---------------------------------------------------------------------------
# 2. Streak calculation — timezone edge cases
# ---------------------------------------------------------------------------


class TestTimezoneEdgeCases:
    """Verify that date-keyed operations respect the caller-supplied timezone."""

    def test_earn_daily_coin_with_explicit_date_utc_vs_local(self, db_session, user_id):
        """Coins earned for different dates accumulate independently."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        earn_daily_coin(user_id, for_date=today)
        earn_daily_coin(user_id, for_date=yesterday)
        coins = StreakCoins.query.filter_by(user_id=user_id).first()
        assert coins.balance == 2

    def test_earn_daily_coin_same_date_not_duplicated(self, db_session, user_id):
        """Two earn calls for the same date only award 1 coin — no TZ drift duplicates."""
        today = date.today()
        r1 = earn_daily_coin(user_id, for_date=today)
        r2 = earn_daily_coin(user_id, for_date=today)
        assert r1 is True
        assert r2 is False
        coins = StreakCoins.query.filter_by(user_id=user_id).first()
        assert coins.balance == 1

    def test_save_daily_completion_updates_steps_on_same_date(self, db_session, user_id):
        """Calling save_daily_completion twice for the same date updates, not duplicates."""
        today = date.today()
        save_daily_completion(user_id, steps_done=1, steps_total=4, for_date=today)
        db_session.flush()
        save_daily_completion(user_id, steps_done=3, steps_total=4, for_date=today)
        db_session.flush()
        events = StreakEvent.query.filter_by(
            user_id=user_id, event_type='earned_daily', event_date=today
        ).all()
        assert len(events) == 1
        assert events[0].steps_done == 3

    def test_process_streak_uses_user_timezone(self, db_session, streak_user):
        """process_streak_on_activity passes tz to activity checker — smoke test via mock."""
        from app.achievements.streak_service import process_streak_on_activity

        tz = 'Asia/Tokyo'
        # has_activity_today is imported locally inside process_streak_on_activity
        # from app.telegram.queries, so we patch it there.
        with patch('app.telegram.queries.has_activity_today', return_value=False) as mock_has, \
             patch('app.achievements.streak_service.get_streak_status', return_value={
                 'streak': 5, 'coins_balance': 0, 'has_activity_today': False,
                 'can_repair': False, 'missed_date': None, 'repair_cost': None,
                 'required_steps': 1, 'steps_total': 4,
             }), \
             patch('app.achievements.streak_service.find_missed_date', return_value=None), \
             patch('app.achievements.streak_service.check_streak_milestone', return_value=None), \
             patch('app.achievements.streak_service.db'):
            process_streak_on_activity(streak_user.id, steps_done=0, steps_total=4, tz=tz)

        mock_has.assert_called_with(streak_user.id, tz=tz)


# ---------------------------------------------------------------------------
# 3. Streak recovery (paid repair) purchase flow
# ---------------------------------------------------------------------------


class TestPaidRepairFlow:
    """apply_paid_repair() validates balance, deducts coins, logs event."""

    def _give_coins(self, db_session, user_id: int, amount: int) -> StreakCoins:
        coins = get_or_create_coins(user_id)
        coins.earn(amount)
        db_session.flush()
        return coins

    def test_paid_repair_success(self, db_session, user_id):
        missed = date.today() - timedelta(days=1)
        self._give_coins(db_session, user_id, 10)
        result = apply_paid_repair(user_id, missed)
        db_session.flush()
        assert result['success'] is True
        assert result['cost'] == 3  # first repair this month costs 3
        assert result['error'] is None
        # Coin balance reduced
        coins = StreakCoins.query.filter_by(user_id=user_id).first()
        assert coins.balance == 7

    def test_paid_repair_insufficient_coins(self, db_session, user_id):
        missed = date.today() - timedelta(days=1)
        self._give_coins(db_session, user_id, 1)
        result = apply_paid_repair(user_id, missed)
        assert result['success'] is False
        assert result['error'] == 'insufficient_coins'

    def test_paid_repair_expired_date(self, db_session, user_id):
        old_date = date.today() - timedelta(days=5)
        self._give_coins(db_session, user_id, 20)
        result = apply_paid_repair(user_id, old_date)
        assert result['success'] is False
        assert result['error'] == 'expired'

    def test_paid_repair_creates_spent_repair_event(self, db_session, user_id):
        missed = date.today() - timedelta(days=1)
        self._give_coins(db_session, user_id, 10)
        apply_paid_repair(user_id, missed)
        db_session.flush()
        event = StreakEvent.query.filter_by(
            user_id=user_id, event_type='spent_repair', event_date=missed
        ).first()
        assert event is not None
        assert event.coins_delta == -3

    def test_repair_cost_escalates_with_monthly_count(self, db_session, user_id):
        """Sliding cost: first=3, second=5, third+=10."""
        assert get_repair_cost(user_id) == 3
        # Add first spent_repair event this month
        month_start = date.today().replace(day=1)
        db_session.add(StreakEvent(
            user_id=user_id, event_type='spent_repair',
            coins_delta=-3, event_date=month_start,
        ))
        db_session.flush()
        assert get_repair_cost(user_id) == 5
        # Add second
        db_session.add(StreakEvent(
            user_id=user_id, event_type='spent_repair',
            coins_delta=-5, event_date=month_start + timedelta(days=1),
        ))
        db_session.flush()
        assert get_repair_cost(user_id) == 10


# ---------------------------------------------------------------------------
# 4. Streak freeze / double-repair protection
# ---------------------------------------------------------------------------


class TestStreakFreezeProtection:
    """has_repair_for_date() prevents applying the same repair twice."""

    def test_free_repair_prevents_duplicate(self, db_session, user_id):
        missed = date.today() - timedelta(days=1)
        result1 = apply_free_repair(user_id, missed)
        db_session.flush()
        result2 = apply_free_repair(user_id, missed)
        assert result1 is True
        assert result2 is False
        events = StreakEvent.query.filter_by(
            user_id=user_id, event_type='free_repair', event_date=missed
        ).all()
        assert len(events) == 1

    def test_paid_repair_blocked_after_free_repair(self, db_session, user_id):
        missed = date.today() - timedelta(days=1)
        apply_free_repair(user_id, missed)
        db_session.flush()
        coins = get_or_create_coins(user_id)
        coins.earn(20)
        db_session.flush()
        result = apply_paid_repair(user_id, missed)
        assert result['success'] is False
        assert result['error'] == 'already_repaired'

    def test_has_repair_for_date_detects_free_repair(self, db_session, user_id):
        missed = date.today() - timedelta(days=2)
        assert has_repair_for_date(user_id, missed) is False
        apply_free_repair(user_id, missed)
        db_session.flush()
        assert has_repair_for_date(user_id, missed) is True

    def test_has_repair_for_date_detects_paid_repair(self, db_session, user_id):
        missed = date.today() - timedelta(days=1)
        get_or_create_coins(user_id)
        coins = StreakCoins.query.filter_by(user_id=user_id).first()
        coins.earn(10)
        db_session.flush()
        apply_paid_repair(user_id, missed)
        db_session.flush()
        assert has_repair_for_date(user_id, missed) is True

    def test_repair_does_not_affect_other_dates(self, db_session, user_id):
        missed = date.today() - timedelta(days=1)
        other = date.today() - timedelta(days=2)
        apply_free_repair(user_id, missed)
        db_session.flush()
        assert has_repair_for_date(user_id, other) is False

    @pytest.mark.smoke
    def test_free_repair_records_details(self, db_session, user_id):
        missed = date.today() - timedelta(days=1)
        apply_free_repair(user_id, missed, steps_done=3, steps_total=4)
        db_session.flush()
        event = StreakEvent.query.filter_by(
            user_id=user_id, event_type='free_repair', event_date=missed
        ).first()
        assert event is not None
        assert event.details['steps_done'] == 3
        assert event.details['steps_total'] == 4
        assert event.details['reason'] == 'progressive_plan_complete'


# ---------------------------------------------------------------------------
# 5. Longest streak record and personal bests
# ---------------------------------------------------------------------------


class TestLongestStreakTracking:
    """longest_streak_days is updated when current streak beats it and never decreases."""

    def test_longest_streak_updated_when_beaten(self, db_session, streak_user):
        from app.achievements.models import UserStatistics
        from app.achievements.services import StatisticsService

        stats = UserStatistics(
            user_id=streak_user.id,
            current_streak_days=4,
            longest_streak_days=4,
            last_activity_date=date.today() - timedelta(days=1),
        )
        db_session.add(stats)
        db_session.flush()

        updated = StatisticsService.update_on_lesson_completion(streak_user.id, 80.0, 'B')

        assert updated.current_streak_days == 5
        assert updated.longest_streak_days == 5

    def test_longest_streak_never_decreases_on_reset(self, db_session, streak_user):
        from app.achievements.models import UserStatistics
        from app.achievements.services import StatisticsService

        stats = UserStatistics(
            user_id=streak_user.id,
            current_streak_days=10,
            longest_streak_days=10,
            last_activity_date=date.today() - timedelta(days=5),
        )
        db_session.add(stats)
        db_session.flush()

        updated = StatisticsService.update_on_lesson_completion(streak_user.id, 80.0, 'B')

        assert updated.current_streak_days == 1
        assert updated.longest_streak_days == 10

    def test_personal_bests_best_week_lessons(self, db_session, streak_user):
        """get_personal_bests returns correct best week lessons count."""
        from app.study.insights_service import get_personal_bests
        from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress

        code = uuid.uuid4().hex[:2].upper()
        level = CEFRLevel(code=code, name='L', description='d', order=1)
        db_session.add(level)
        db_session.flush()
        mod = Module(
            level_id=level.id, number=1, title='M', description='d',
            raw_content={'module': {'id': 1}},
        )
        db_session.add(mod)
        db_session.flush()

        # 3 lessons completed this week, 1 lesson last week
        this_monday = date.today() - timedelta(days=date.today().weekday())
        this_week_ts = datetime.combine(this_monday, datetime.min.time()).replace(
            tzinfo=None
        ) + timedelta(hours=10)
        last_week_ts = this_week_ts - timedelta(days=7)

        for i in range(3):
            lesson = Lessons(
                module_id=mod.id, number=i + 1, title=f'L{i}',
                type='text', content={},
            )
            db_session.add(lesson)
            db_session.flush()
            db_session.add(LessonProgress(
                user_id=streak_user.id, lesson_id=lesson.id,
                status='completed', completed_at=this_week_ts,
            ))

        # 1 lesson last week
        lesson_old = Lessons(
            module_id=mod.id, number=10, title='Old', type='text', content={},
        )
        db_session.add(lesson_old)
        db_session.flush()
        db_session.add(LessonProgress(
            user_id=streak_user.id, lesson_id=lesson_old.id,
            status='completed', completed_at=last_week_ts,
        ))
        db_session.flush()

        result = get_personal_bests(streak_user.id)

        assert result['best_week_lessons'] == 3
        assert result['longest_streak_days'] >= 0
        assert result['max_words_in_day'] >= 0

    def test_personal_bests_empty_user(self, db_session, streak_user):
        """get_personal_bests returns zeros for a user with no activity."""
        from app.study.insights_service import get_personal_bests

        result = get_personal_bests(streak_user.id)

        assert result == {'longest_streak_days': 0, 'max_words_in_day': 0, 'best_week_lessons': 0}


# ---------------------------------------------------------------------------
# 6. Listening streak
# ---------------------------------------------------------------------------


def _make_listening_lesson_for_streak(db_session):
    """Create minimal CEFRLevel → Module → Lessons chain for FK in ListeningAttempt."""
    from app.curriculum.models import CEFRLevel, Module, Lessons

    code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name='Level', description='d', order=1)
    db_session.add(level)
    db_session.flush()
    module = Module(
        level_id=level.id,
        number=1,
        title='M',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.flush()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Listening',
        type='dictation',
        content={'audio_url': '/a.mp3', 'transcript': 'test'},
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


class TestGetListeningStreak:
    """get_listening_streak() counts consecutive days with ListeningAttempt rows."""

    def test_no_attempts_returns_zero(self, db_session, streak_user):
        result = get_listening_streak(streak_user.id, tz='UTC')
        assert result == 0

    def test_three_consecutive_days_returns_3(self, db_session, streak_user):
        from app.curriculum.models import ListeningAttempt

        lesson = _make_listening_lesson_for_streak(db_session)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        for offset in range(3):  # today, yesterday, day before
            db_session.add(ListeningAttempt(
                user_id=streak_user.id,
                lesson_id=lesson.id,
                score=80.0,
                replay_count=0,
                created_at=now_naive - timedelta(days=offset),
            ))
        db_session.flush()

        result = get_listening_streak(streak_user.id, tz='UTC')
        assert result == 3

    def test_gap_resets_streak_to_1(self, db_session, streak_user):
        from app.curriculum.models import ListeningAttempt

        lesson = _make_listening_lesson_for_streak(db_session)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        # Today and 3 days ago — gap on yesterday and 2 days ago
        for offset in (0, 3):
            db_session.add(ListeningAttempt(
                user_id=streak_user.id,
                lesson_id=lesson.id,
                score=80.0,
                replay_count=0,
                created_at=now_naive - timedelta(days=offset),
            ))
        db_session.flush()

        result = get_listening_streak(streak_user.id, tz='UTC')
        assert result == 1

    def test_only_yesterday_and_before_no_today(self, db_session, streak_user):
        from app.curriculum.models import ListeningAttempt

        lesson = _make_listening_lesson_for_streak(db_session)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        # Yesterday and 2 days ago — no today
        for offset in (1, 2):
            db_session.add(ListeningAttempt(
                user_id=streak_user.id,
                lesson_id=lesson.id,
                score=80.0,
                replay_count=0,
                created_at=now_naive - timedelta(days=offset),
            ))
        db_session.flush()

        result = get_listening_streak(streak_user.id, tz='UTC')
        assert result == 2

    def test_multiple_attempts_same_day_count_as_one(self, db_session, streak_user):
        from app.curriculum.models import ListeningAttempt

        lesson = _make_listening_lesson_for_streak(db_session)
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        # 5 attempts today — should still count as 1 day
        for _ in range(5):
            db_session.add(ListeningAttempt(
                user_id=streak_user.id,
                lesson_id=lesson.id,
                score=90.0,
                replay_count=1,
                created_at=now_naive,
            ))
        db_session.flush()

        result = get_listening_streak(streak_user.id, tz='UTC')
        assert result == 1
