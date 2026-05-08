"""Linear plan slot_completed activity ping (Task 13).

Each successful linear-slot XP award emits a
``DailyPlanEvent(event_type='linear_slot_completed', step_kind=source)``.
Duplicate calls the same day must NOT add a second event row, mirroring
the StreakEvent dedup contract of ``award_linear_slot_xp_idempotent``.
"""
from __future__ import annotations

import uuid
from datetime import date

from app.achievements.models import UserStatistics
from app.auth.models import User
from app.daily_plan.linear.xp import award_linear_slot_xp_idempotent
from app.daily_plan.models import DailyPlanEvent
from app.utils.db import db as real_db


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'linevt_{suffix}',
        email=f'linevt_{suffix}@example.com',
        active=True,
        use_linear_plan=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    db_session.add(UserStatistics(user_id=user.id, total_xp=0, current_streak_days=0))
    db_session.commit()
    return user


def _slot_events(user_id: int) -> list[DailyPlanEvent]:
    return (
        DailyPlanEvent.query.filter_by(
            user_id=user_id, event_type='linear_slot_completed'
        )
        .order_by(DailyPlanEvent.id.asc())
        .all()
    )


def test_first_of_day_emits_slot_completed_event(db_session):
    user = _make_user(db_session)
    today = date(2026, 4, 20)

    result = award_linear_slot_xp_idempotent(
        user.id, 'linear_curriculum_card', today, real_db,
    )
    db_session.commit()

    assert result is not None
    events = _slot_events(user.id)
    assert len(events) == 1
    assert events[0].step_kind == 'curriculum_card'
    assert events[0].plan_date == today


def test_duplicate_call_same_day_does_not_emit_second_event(db_session):
    user = _make_user(db_session)
    today = date(2026, 4, 20)

    award_linear_slot_xp_idempotent(user.id, 'linear_srs_global', today, real_db)
    db_session.commit()
    second = award_linear_slot_xp_idempotent(user.id, 'linear_srs_global', today, real_db)
    db_session.commit()

    assert second is None
    events = _slot_events(user.id)
    assert len(events) == 1
    assert events[0].step_kind == 'srs_global'


def test_different_sources_emit_independent_events(db_session):
    user = _make_user(db_session)
    today = date(2026, 4, 20)

    award_linear_slot_xp_idempotent(user.id, 'linear_curriculum_card', today, real_db)
    award_linear_slot_xp_idempotent(user.id, 'linear_srs_global', today, real_db)
    award_linear_slot_xp_idempotent(user.id, 'linear_book_reading', today, real_db)
    db_session.commit()

    kinds = sorted(ev.step_kind for ev in _slot_events(user.id))
    assert kinds == ['book_reading', 'curriculum_card', 'srs_global']


def test_unknown_source_does_not_emit(db_session):
    user = _make_user(db_session)
    result = award_linear_slot_xp_idempotent(
        user.id, 'linear_bogus', date(2026, 4, 20), real_db,
    )
    db_session.commit()

    assert result is None
    assert _slot_events(user.id) == []
