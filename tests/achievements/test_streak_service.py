"""Unit tests for the achievement streak service.

Covers:
- Streak calculation with timezone edge cases
- Streak recovery purchase flow (paid repair)
- Streak freeze / double-repair protection handling
"""
from datetime import date, timedelta
from unittest.mock import patch, MagicMock
import uuid

import pytest

from app.auth.models import User
from app.achievements.models import StreakCoins, StreakEvent
from app.achievements.streak_service import (
    apply_free_repair,
    apply_paid_repair,
    earn_daily_coin,
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
