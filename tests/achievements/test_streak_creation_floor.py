"""New learners cannot acquire repaired study days before registration.

These integration tests use a disposable SQLite database, not local user data.
The real activity queries, timezone conversion and repair writers all run.
"""
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from freezegun import freeze_time

from app.achievements.models import StreakCoins, StreakEvent
from app.achievements.streak_service import (
    _repair_creation_floor,
    apply_free_repair,
    apply_paid_repair,
    apply_shield_repair,
    auto_heal_streak_on_activity,
    find_auto_heal_date,
    find_missed_date,
    get_or_create_coins,
    process_streak_on_activity,
)
from app.auth.models import User
from app.utils.db import db
from app.utils.time_utils import study_day_date_for_tz, study_day_start_utc
from config.settings import DEFAULT_TIMEZONE
from tests.api.test_account_deletion import native_app as _native_app


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture(autouse=True)
def rollback_test(native_app):
    yield
    db.session.rollback()


def account(created_at, *, tz="Europe/Moscow"):
    name = "streak_floor_" + uuid4().hex
    user = User(username=name, email=name + "@example.invalid", active=True,
                created_at=created_at, timezone=tz, streak_shield_active=True)
    user.set_password("disposable-streak-test-password")
    db.session.add(user)
    db.session.flush()
    return user


def activity(user, study_day):
    # Place genuine XP activity after the beginning of this user's study day.
    instant = study_day_start_utc(user.timezone or DEFAULT_TIMEZONE, study_day) + timedelta(hours=1)
    if study_day == study_day_date_for_tz(user.timezone or DEFAULT_TIMEZONE):
        instant = datetime.now(UTC)
    db.session.add(StreakEvent(user_id=user.id, event_type="xp_linear",
                               coins_delta=0, event_date=study_day,
                               created_at=instant.replace(tzinfo=None)))
    db.session.flush()


def repairs(user):
    return StreakEvent.query.filter(
        StreakEvent.user_id == user.id,
        StreakEvent.event_type.in_(["free_repair", "spent_repair", "shield_repair", "repair_refund"]),
    ).order_by(StreakEvent.event_date).all()


@freeze_time("2026-11-19 11:14:33")
def test_first_activity_does_not_heal_three_days_before_new_account(native_app):
    user = account(datetime(2026, 11, 19, 11, 6))
    activity(user, date(2026, 11, 19))
    assert find_auto_heal_date(user.id, user.timezone) is None
    assert find_missed_date(user.id, user.timezone) is None
    assert auto_heal_streak_on_activity(user.id, user.timezone) == 0
    assert repairs(user) == []
    assert user.streak_shield_active is True


@freeze_time("2026-11-19 11:14:33")
def test_full_activity_processing_keeps_new_learner_streak_at_one(native_app):
    user = account(datetime(2026, 11, 19, 11, 6))
    activity(user, date(2026, 11, 19))
    with patch("app.achievements.services.check_weekly_milestone_achievements"):
        result = process_streak_on_activity(user.id, steps_done=0, steps_total=2)
    assert result["streak_status"]["streak"] == 1
    assert result["streak_repaired"] is False
    assert repairs(user) == []
    assert user.streak_shield_active is True


@freeze_time("2026-11-20 12:00:00")
@pytest.mark.parametrize("writer", [apply_free_repair, apply_shield_repair, apply_paid_repair])
def test_direct_repair_cannot_write_pre_registration_day_or_spend_coins(native_app, writer):
    user = account(datetime(2026, 11, 20, 8))
    coins = get_or_create_coins(user.id)
    coins.earn(20)
    db.session.flush()
    result = writer(user.id, date(2026, 11, 19))
    if writer is apply_paid_repair:
        assert result == {"success": False, "cost": 0, "balance": 0, "error": "before_registration"}
    else:
        assert result is False
    db.session.flush()
    assert repairs(user) == []
    assert coins.balance == coins.total_earned == 20 and coins.total_spent == 0
    assert user.streak_shield_active is True


@pytest.mark.parametrize(("tz", "created", "expected"), [
    ("UTC", datetime(2026, 11, 20, 1, 59, 59), date(2026, 11, 19)),
    ("UTC", datetime(2026, 11, 20, 2), date(2026, 11, 20)),
    ("Europe/Moscow", datetime(2026, 11, 19, 22, 59, 59), date(2026, 11, 19)),
    ("Europe/Moscow", datetime(2026, 11, 19, 23), date(2026, 11, 20)),
    ("Asia/Tokyo", datetime(2026, 11, 19, 16, 59, 59), date(2026, 11, 19)),
    ("Asia/Tokyo", datetime(2026, 11, 19, 17, tzinfo=UTC), date(2026, 11, 20)),
    ("America/New_York", datetime(2026, 11, 20, 6, 59, 59), date(2026, 11, 19)),
    ("America/New_York", datetime(2026, 11, 20, 7), date(2026, 11, 20)),
    ("America/New_York", datetime(2026, 11, 1, 5, 59, 59), date(2026, 10, 31)),
    ("America/New_York", datetime(2026, 11, 1, 6, 59, 59), date(2026, 10, 31)),
    ("America/New_York", datetime(2026, 11, 1, 7), date(2026, 11, 1)),
    ("America/New_York", datetime(2026, 3, 8, 6, 59, 59), date(2026, 3, 7)),
    ("America/New_York", datetime(2026, 3, 8, 7), date(2026, 3, 8)),
    ("Pacific/Kiritimati", datetime(2026, 11, 19, 12), date(2026, 11, 20)),
])
def test_creation_floor_uses_account_timezone_and_exact_two_am_boundary(native_app, tz, created, expected):
    user = account(created, tz=tz)
    assert _repair_creation_floor(user.id) == expected
    assert apply_free_repair(user.id, expected - timedelta(days=1)) is False
    assert apply_free_repair(user.id, expected) is True
    db.session.flush()
    assert [event.event_date for event in repairs(user)] == [expected]


def test_unknown_or_missing_timezone_retains_existing_discovery_fallback(native_app):
    created = datetime(2026, 11, 19, 23, 30)
    expected = study_day_date_for_tz(DEFAULT_TIMEZONE, now_utc=created)
    for tz in [None, "Mars/Olympus"]:
        user = account(created, tz=tz)
        assert _repair_creation_floor(user.id) == expected


@freeze_time("2026-11-20 00:30:00")  # 03:30 in Moscow: a new study day has begun.
def test_registration_just_before_two_am_can_repair_its_first_study_day_only(native_app):
    user = account(datetime(2026, 11, 19, 22, 59, 59))  # 01:59:59 local on Nov 20.
    activity(user, date(2026, 11, 20))
    assert find_auto_heal_date(user.id, user.timezone) == date(2026, 11, 19)
    assert auto_heal_streak_on_activity(user.id, user.timezone) == 1
    assert [event.event_date for event in repairs(user)] == [date(2026, 11, 19)]
    assert find_auto_heal_date(user.id, user.timezone) is None


@freeze_time("2026-11-20 00:30:00")
def test_registration_at_two_am_cannot_repair_the_previous_study_day(native_app):
    user = account(datetime(2026, 11, 19, 23))
    activity(user, date(2026, 11, 20))
    assert auto_heal_streak_on_activity(user.id, user.timezone) == 0
    assert repairs(user) == []


@freeze_time("2026-11-20 12:00:00")
def test_established_account_keeps_three_day_grace_window_and_refunds(native_app):
    user = account(datetime(2025, 1, 1))
    activity(user, date(2026, 11, 20))
    coins = get_or_create_coins(user.id)
    coins.earn(20)
    db.session.flush()
    assert apply_paid_repair(user.id, date(2026, 11, 19))["success"] is True
    assert coins.balance == 17
    assert auto_heal_streak_on_activity(user.id, user.timezone) == 3
    assert coins.balance == 20
    free = [event for event in repairs(user) if event.event_type == "free_repair"]
    assert [event.event_date for event in free] == [date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19)]
    assert len([event for event in repairs(user) if event.event_type == "repair_refund"]) == 1
    assert find_auto_heal_date(user.id, user.timezone) is None


@freeze_time("2026-11-20 12:00:00")
def test_legacy_unknown_creation_time_keeps_repair_behaviour(native_app):
    user = account(datetime(2025, 1, 1))
    user.created_at = None  # Set after INSERT so SQLAlchemy's default cannot replace NULL.
    db.session.flush()
    activity(user, date(2026, 11, 20))
    assert _repair_creation_floor(user.id) is None
    assert auto_heal_streak_on_activity(user.id, user.timezone) == 3
    assert len(repairs(user)) == 3


@freeze_time("2026-11-20 12:00:00")
def test_historical_pre_registration_repairs_are_retained_without_refund_or_extension(native_app):
    user = account(datetime(2026, 11, 20, 8))
    activity(user, date(2026, 11, 20))
    coins = get_or_create_coins(user.id)
    coins.earn(10)
    legacy = StreakEvent(user_id=user.id, event_type="spent_repair", coins_delta=-3,
                         event_date=date(2026, 11, 19), details={"legacy": True})
    db.session.add(legacy)
    db.session.flush()
    identifier = legacy.id
    assert auto_heal_streak_on_activity(user.id, user.timezone) == 0
    assert find_missed_date(user.id, user.timezone) is None
    assert [(event.id, event.event_type, event.event_date, event.details) for event in repairs(user)] == [
        (identifier, "spent_repair", date(2026, 11, 19), {"legacy": True})]
    assert coins.balance == 10


@freeze_time("2026-11-20 12:00:00")
def test_paid_repair_discovery_cannot_walk_past_creation_even_with_old_activity(native_app):
    user = account(datetime(2026, 11, 20, 8))
    activity(user, date(2026, 11, 18))  # Simulate an imported historical row.
    assert find_missed_date(user.id, user.timezone) is None
    assert find_auto_heal_date(user.id, user.timezone) is None


@freeze_time("2026-11-20 12:00:00")
def test_established_paid_and_shield_repairs_still_work(native_app):
    user = account(datetime(2025, 1, 1))
    activity(user, date(2026, 11, 18))
    assert find_missed_date(user.id, user.timezone) == date(2026, 11, 19)
    coins = get_or_create_coins(user.id)
    coins.earn(20)
    assert apply_paid_repair(user.id, date(2026, 11, 19))["success"] is True
    assert apply_shield_repair(user.id, date(2026, 11, 18)) is True
    assert apply_free_repair(user.id, date(2026, 11, 17)) is True
    db.session.flush()
    assert coins.balance == 17
    assert len(repairs(user)) == 3


@freeze_time("2026-11-20 12:00:00")
def test_different_discovery_timezone_cannot_refund_a_day_before_stored_account_floor(native_app):
    user = account(datetime(2026, 11, 20, 0), tz="Asia/Tokyo")
    activity(user, date(2026, 11, 20))
    coins = get_or_create_coins(user.id)
    coins.earn(10)
    db.session.add(StreakEvent(user_id=user.id, event_type="spent_repair", coins_delta=-3,
                               event_date=date(2026, 11, 19)))
    db.session.flush()
    assert find_auto_heal_date(user.id, "America/Los_Angeles") == date(2026, 11, 19)
    assert auto_heal_streak_on_activity(user.id, "America/Los_Angeles") == 0
    assert coins.balance == 10
    assert [event.event_type for event in repairs(user)] == ["spent_repair"]


def test_rejecting_paid_repair_does_not_even_create_a_coin_wallet(native_app):
    user = account(datetime(2026, 11, 20))
    assert apply_paid_repair(user.id, date(2026, 11, 18))["error"] == "before_registration"
    assert StreakCoins.query.filter_by(user_id=user.id).first() is None
