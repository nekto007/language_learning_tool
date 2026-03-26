"""Tests for streak recovery system: coins, free/paid repair."""
import uuid
from datetime import date, timedelta

import pytest

from app.achievements.models import StreakCoins, StreakEvent
from app.achievements.streak_service import (
    apply_free_repair,
    apply_paid_repair,
    earn_daily_coin,
    get_or_create_coins,
    get_repair_cost,
    has_repair_for_date,
)


@pytest.fixture
def user_id(db_session):
    """Create a test user and return their ID."""
    from app.auth.models import User
    u = User(username=f'streak_test_{uuid.uuid4().hex[:8]}', email=f'{uuid.uuid4().hex[:8]}@test.com')
    u.set_password('test123')
    db_session.add(u)
    db_session.flush()
    return u.id


@pytest.fixture(autouse=True)
def cleanup_streak(db_session, user_id):
    """Clean up streak tables after each test."""
    yield
    StreakEvent.query.filter_by(user_id=user_id).delete()
    StreakCoins.query.filter_by(user_id=user_id).delete()
    db_session.commit()


class TestEarnDailyCoin:
    def test_earn_first_coin(self, db_session, user_id):
        result = earn_daily_coin(user_id)
        assert result is True
        coins = StreakCoins.query.filter_by(user_id=user_id).first()
        assert coins.balance == 1
        assert coins.total_earned == 1

    def test_no_duplicate_earn(self, db_session, user_id):
        earn_daily_coin(user_id)
        result = earn_daily_coin(user_id)
        assert result is False
        coins = StreakCoins.query.filter_by(user_id=user_id).first()
        assert coins.balance == 1

    def test_earn_different_days(self, db_session, user_id):
        today = date.today()
        earn_daily_coin(user_id, for_date=today)
        earn_daily_coin(user_id, for_date=today - timedelta(days=1))
        coins = StreakCoins.query.filter_by(user_id=user_id).first()
        assert coins.balance == 2
        assert coins.total_earned == 2


class TestGetOrCreateCoins:
    def test_create_new(self, db_session, user_id):
        coins = get_or_create_coins(user_id)
        assert coins.balance == 0
        assert coins.user_id == user_id

    def test_get_existing(self, db_session, user_id):
        c1 = get_or_create_coins(user_id)
        c1.balance = 10
        db_session.flush()
        c2 = get_or_create_coins(user_id)
        assert c2.balance == 10
        assert c1.id == c2.id


class TestRepairCost:
    def test_first_repair_costs_3(self, db_session, user_id):
        assert get_repair_cost(user_id) == 3

    def test_second_repair_costs_5(self, db_session, user_id):
        db_session.add(StreakEvent(
            user_id=user_id, event_type='spent_repair',
            coins_delta=-3, event_date=date.today(),
        ))
        db_session.flush()
        assert get_repair_cost(user_id) == 5

    def test_third_repair_costs_10(self, db_session, user_id):
        for i in range(2):
            db_session.add(StreakEvent(
                user_id=user_id, event_type='spent_repair',
                coins_delta=-3, event_date=date.today() - timedelta(days=i),
            ))
        db_session.flush()
        assert get_repair_cost(user_id) == 10


class TestFreeRepair:
    def test_apply_free_repair(self, db_session, user_id):
        yesterday = date.today() - timedelta(days=1)
        result = apply_free_repair(user_id, yesterday)
        assert result is True
        assert has_repair_for_date(user_id, yesterday) is True

    def test_no_double_repair(self, db_session, user_id):
        yesterday = date.today() - timedelta(days=1)
        apply_free_repair(user_id, yesterday)
        result = apply_free_repair(user_id, yesterday)
        assert result is False


class TestPaidRepair:
    def test_successful_repair(self, db_session, user_id):
        coins = get_or_create_coins(user_id)
        coins.earn(10)
        db_session.flush()

        yesterday = date.today() - timedelta(days=1)
        result = apply_paid_repair(user_id, yesterday)
        assert result['success'] is True
        assert result['cost'] == 3
        assert result['balance'] == 7

    def test_insufficient_coins(self, db_session, user_id):
        get_or_create_coins(user_id)  # balance=0
        db_session.flush()

        yesterday = date.today() - timedelta(days=1)
        result = apply_paid_repair(user_id, yesterday)
        assert result['success'] is False
        assert result['error'] == 'insufficient_coins'

    def test_expired_repair(self, db_session, user_id):
        coins = get_or_create_coins(user_id)
        coins.earn(10)
        db_session.flush()

        old_date = date.today() - timedelta(days=3)
        result = apply_paid_repair(user_id, old_date)
        assert result['success'] is False
        assert result['error'] == 'expired'

    def test_already_repaired(self, db_session, user_id):
        coins = get_or_create_coins(user_id)
        coins.earn(10)
        db_session.flush()

        yesterday = date.today() - timedelta(days=1)
        apply_paid_repair(user_id, yesterday)
        result = apply_paid_repair(user_id, yesterday)
        assert result['success'] is False
        assert result['error'] == 'already_repaired'


class TestCoinsSpendEarn:
    def test_spend_success(self, db_session, user_id):
        coins = get_or_create_coins(user_id)
        coins.earn(5)
        assert coins.spend(3) is True
        assert coins.balance == 2
        assert coins.total_spent == 3

    def test_spend_insufficient(self, db_session, user_id):
        coins = get_or_create_coins(user_id)
        coins.earn(2)
        assert coins.spend(5) is False
        assert coins.balance == 2
        assert coins.total_spent == 0
