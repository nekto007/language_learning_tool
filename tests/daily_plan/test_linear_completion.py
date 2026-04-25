"""Tests for ``maybe_record_linear_plan_completion`` (Task 9).

Linear plan completions must increment ``UserStatistics.plans_completed_total``
and trigger ``record_plan_completion``'s rank-up detection. The helper is
idempotent per (user, date) via the existing ``StreakEvent('plan_completed')``
marker used by the mission flow.
"""
from __future__ import annotations

import uuid
from datetime import date

from app.achievements.models import StreakEvent, UserStatistics
from app.auth.models import User
from app.daily_plan.linear.xp import maybe_record_linear_plan_completion
from app.utils.db import db as real_db


def _make_user(db_session, *, use_linear_plan=True, plans_completed=0) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'lincomp_{suffix}',
        email=f'lincomp_{suffix}@example.com',
        active=True,
        use_linear_plan=use_linear_plan,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    db_session.add(UserStatistics(
        user_id=user.id,
        total_xp=0,
        current_streak_days=0,
        plans_completed_total=plans_completed,
    ))
    db_session.commit()
    return user


def _stats(user_id: int) -> UserStatistics:
    return UserStatistics.query.filter_by(user_id=user_id).first()


def _make_plan(slots_completed: list[bool]) -> tuple[dict, dict]:
    kinds = ['curriculum', 'srs', 'reading'][: len(slots_completed)]
    plan = {
        'mode': 'linear',
        'baseline_slots': [
            {'kind': k, 'completed': c} for k, c in zip(kinds, slots_completed)
        ],
    }
    plan_completion = {k: c for k, c in zip(kinds, slots_completed)}
    return plan, plan_completion


def test_records_completion_when_day_secured(db_session):
    user = _make_user(db_session)
    plan, completion = _make_plan([True, True, True])
    today = date(2026, 4, 25)

    rank_up = maybe_record_linear_plan_completion(
        user.id, plan, completion, today, real_db,
    )
    db_session.commit()

    assert _stats(user.id).plans_completed_total == 1
    markers = StreakEvent.query.filter_by(
        user_id=user.id, event_type='plan_completed', event_date=today,
    ).all()
    assert len(markers) == 1
    # First completion crosses the explorer threshold only at 7 plans, so
    # rank_up is None here — but the call itself must succeed.
    assert rank_up is None


def test_idempotent_per_day(db_session):
    user = _make_user(db_session)
    plan, completion = _make_plan([True, True, True])
    today = date(2026, 4, 25)

    maybe_record_linear_plan_completion(user.id, plan, completion, today, real_db)
    db_session.commit()
    maybe_record_linear_plan_completion(user.id, plan, completion, today, real_db)
    db_session.commit()

    assert _stats(user.id).plans_completed_total == 1
    markers = StreakEvent.query.filter_by(
        user_id=user.id, event_type='plan_completed', event_date=today,
    ).all()
    assert len(markers) == 1


def test_noop_when_day_not_secured(db_session):
    user = _make_user(db_session)
    plan, completion = _make_plan([True, False, True])
    today = date(2026, 4, 25)

    result = maybe_record_linear_plan_completion(
        user.id, plan, completion, today, real_db,
    )
    db_session.commit()

    assert result is None
    assert _stats(user.id).plans_completed_total == 0


def test_skips_non_linear_user(db_session):
    user = _make_user(db_session, use_linear_plan=False)
    plan, completion = _make_plan([True, True, True])
    today = date(2026, 4, 25)

    result = maybe_record_linear_plan_completion(
        user.id, plan, completion, today, real_db,
    )
    db_session.commit()

    assert result is None
    assert _stats(user.id).plans_completed_total == 0


def test_noop_when_no_baseline_slots(db_session):
    user = _make_user(db_session)
    plan = {'mode': 'linear', 'baseline_slots': []}
    today = date(2026, 4, 25)

    result = maybe_record_linear_plan_completion(
        user.id, plan, {}, today, real_db,
    )
    db_session.commit()

    assert result is None
    assert _stats(user.id).plans_completed_total == 0


def test_rank_up_returned_at_threshold(db_session):
    user = _make_user(db_session, plans_completed=6)
    plan, completion = _make_plan([True, True, True])
    today = date(2026, 4, 25)

    rank_up = maybe_record_linear_plan_completion(
        user.id, plan, completion, today, real_db,
    )
    db_session.commit()

    assert rank_up is not None
    assert rank_up.previous_code == 'novice'
    assert rank_up.new_code == 'explorer'
    assert _stats(user.id).plans_completed_total == 7
    assert _stats(user.id).current_rank == 'explorer'
