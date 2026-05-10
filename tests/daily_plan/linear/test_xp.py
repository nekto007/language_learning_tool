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
from app.achievements.xp_service import LINEAR_XP
from app.auth.models import User
from app.daily_plan.linear.xp import award_linear_slot_xp_idempotent, maybe_award_writing_xp
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


# ---------------------------------------------------------------------------
# maybe_award_writing_xp tests (Task 24)
# ---------------------------------------------------------------------------

def _make_linear_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'wrxp_{suffix}',
        email=f'wrxp_{suffix}@example.com',
        active=True,
        use_linear_plan=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    db_session.add(UserStatistics(user_id=user.id, total_xp=0, current_streak_days=0))
    db_session.commit()
    return user


def test_writing_xp_registered_in_linear_xp():
    assert 'linear_writing' in LINEAR_XP
    assert LINEAR_XP['linear_writing'] == 25


def test_maybe_award_writing_xp_fires_on_first_call(db_session):
    user = _make_linear_user(db_session)
    today = date(2026, 5, 10)

    result = maybe_award_writing_xp(user.id, lesson_id=1, for_date=today, db_session=real_db)
    db_session.commit()

    assert result is not None
    assert result.xp_awarded > 0
    events = _slot_events(user.id)
    assert len(events) == 1
    assert events[0].step_kind == 'writing'
    assert events[0].plan_date == today


def test_maybe_award_writing_xp_is_idempotent_same_day(db_session):
    user = _make_linear_user(db_session)
    today = date(2026, 5, 10)

    first = maybe_award_writing_xp(user.id, lesson_id=1, for_date=today, db_session=real_db)
    db_session.commit()
    second = maybe_award_writing_xp(user.id, lesson_id=2, for_date=today, db_session=real_db)
    db_session.commit()

    assert first is not None
    assert second is None
    assert len(_slot_events(user.id)) == 1


def test_maybe_award_writing_xp_noop_for_non_linear_user(db_session):
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'nonlin_{suffix}',
        email=f'nonlin_{suffix}@example.com',
        active=True,
        use_linear_plan=False,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    db_session.add(UserStatistics(user_id=user.id, total_xp=0, current_streak_days=0))
    db_session.commit()

    result = maybe_award_writing_xp(user.id, for_date=date(2026, 5, 10), db_session=real_db)
    db_session.commit()

    assert result is None
    assert _slot_events(user.id) == []


def test_day_secured_unaffected_by_writing_slot():
    from app.daily_plan.linear.plan import compute_linear_day_secured

    baseline = [
        {'kind': 'curriculum', 'completed': True},
        {'kind': 'srs', 'completed': True},
        {'kind': 'reading', 'completed': True},
    ]
    assert compute_linear_day_secured(baseline) is True

    writing_extension = {'kind': 'writing', 'completed': False}
    assert compute_linear_day_secured(baseline + [writing_extension]) is False

    assert compute_linear_day_secured(baseline) is True
