"""Tests for Task 2 of the entity-consistency audit: verify that all
legacy XPService.award_xp callers now route through the unified
``app.achievements.xp_service.award_xp`` which writes to
``UserStatistics.total_xp``, and that the curriculum lesson XP award is
idempotent per (user, lesson, day).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.auth.models import User
from app.curriculum.xp import (
    CURRICULUM_LESSON_EVENT_TYPE,
    award_curriculum_lesson_xp_idempotent,
)
from app.study.services.session_service import SessionService


def _make_user(db_session) -> User:
    username = f'xpunif_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@example.com',
        active=True,
        onboarding_completed=True,
    )
    user.set_password('x')
    db_session.add(user)
    db_session.commit()
    return user


def _stats_total_xp(user_id: int) -> int:
    stats = UserStatistics.query.filter_by(user_id=user_id).first()
    return int(stats.total_xp or 0) if stats else 0


def test_session_service_award_xp_updates_user_statistics(db_session):
    user = _make_user(db_session)

    SessionService.award_xp(user.id, 15, source='cards_session')

    assert _stats_total_xp(user.id) >= 15


def test_session_service_award_xp_zero_is_noop(db_session):
    user = _make_user(db_session)

    SessionService.award_xp(user.id, 0, source='noop')

    assert _stats_total_xp(user.id) == 0


def test_curriculum_lesson_xp_idempotent_same_day(db_session):
    user = _make_user(db_session)
    today = date.today()

    first = award_curriculum_lesson_xp_idempotent(
        user.id, lesson_id=4242, for_date=today, db_session=None
    )
    db_session.commit()
    assert first is not None
    total_after_first = _stats_total_xp(user.id)

    second = award_curriculum_lesson_xp_idempotent(
        user.id, lesson_id=4242, for_date=today, db_session=None
    )
    db_session.commit()
    assert second is None
    assert _stats_total_xp(user.id) == total_after_first

    # Exactly one StreakEvent recorded for this lesson on this date.
    events = (
        StreakEvent.query.filter_by(
            user_id=user.id,
            event_type=CURRICULUM_LESSON_EVENT_TYPE,
            event_date=today,
        )
        .filter(StreakEvent.details['lesson_id'].astext == '4242')
        .all()
    )
    assert len(events) == 1


def test_curriculum_lesson_xp_new_day_awards_again(db_session):
    user = _make_user(db_session)
    yesterday = date.today() - timedelta(days=1)
    today = date.today()

    award_curriculum_lesson_xp_idempotent(
        user.id, lesson_id=99, for_date=yesterday, db_session=None
    )
    db_session.commit()
    xp_after_yesterday = _stats_total_xp(user.id)

    result_today = award_curriculum_lesson_xp_idempotent(
        user.id, lesson_id=99, for_date=today, db_session=None
    )
    db_session.commit()

    assert result_today is not None
    assert _stats_total_xp(user.id) > xp_after_yesterday


def test_curriculum_lesson_xp_different_lessons_both_award(db_session):
    user = _make_user(db_session)
    today = date.today()

    first = award_curriculum_lesson_xp_idempotent(
        user.id, lesson_id=1, for_date=today, db_session=None
    )
    second = award_curriculum_lesson_xp_idempotent(
        user.id, lesson_id=2, for_date=today, db_session=None
    )
    db_session.commit()

    assert first is not None
    assert second is not None
    # Two distinct StreakEvent rows
    events = StreakEvent.query.filter_by(
        user_id=user.id,
        event_type=CURRICULUM_LESSON_EVENT_TYPE,
        event_date=today,
    ).all()
    assert len(events) == 2
