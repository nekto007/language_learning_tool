"""Listening extension slot for the linear daily plan.

Surfaces the next incomplete listening_immersion or dictation lesson
in the user's current curriculum module as an optional extension slot.
Returns ``None`` when no eligible lesson is available — the chain
builder skips it silently.

Completion is keyed on whether the user earned a
``linear_curriculum_listening_immersion`` or ``linear_curriculum_dictation``
XP award today (written by ``maybe_award_curriculum_xp`` from the lesson
grader).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.curriculum_slot import _eta_minutes

logger = logging.getLogger(__name__)

_LISTENING_LESSON_TYPES: frozenset[str] = frozenset({
    'listening_immersion',
    'listening_immersion_quiz',
    'dictation',
})

_LISTENING_XP_SOURCES: frozenset[str] = frozenset({
    'linear_curriculum_listening_immersion',
    'linear_curriculum_dictation',
})

_LISTENING_SLOT_ETA_MINUTES = 10


def _listening_done_today(user_id: int, db: Any) -> bool:
    """Return True when the user already completed a listening lesson today."""
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import (
        LINEAR_XP_EVENT_TYPE,
        get_linear_event_local_date,
    )

    today = get_linear_event_local_date(user_id, db)
    query = db.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.event_date == today,
        StreakEvent.details['source'].astext.in_(list(_LISTENING_XP_SOURCES)),
    )
    return db.session.query(query.exists()).scalar() or False


def _find_next_listening_lesson(user_id: int, db: Any) -> Optional[Lessons]:
    """Return the next incomplete listening lesson in the user's current module.

    Looks within the module of the user's current spine position. Returns
    ``None`` when the current module has no incomplete listening lessons.
    """
    next_lesson = find_next_lesson_linear(user_id, db)
    if next_lesson is None:
        return None

    completed_subq = (
        db.session.query(LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        )
        .subquery()
    )

    return (
        db.session.query(Lessons)
        .filter(
            Lessons.module_id == next_lesson.module_id,
            Lessons.type.in_(list(_LISTENING_LESSON_TYPES)),
            Lessons.id.notin_(db.session.query(completed_subq.c.lesson_id)),
        )
        .order_by(Lessons.number.asc(), Lessons.id.asc())
        .first()
    )


def build_listening_slot(user_id: int, db: Any) -> Optional[LinearSlot]:
    """Build the listening extension slot.

    Returns ``None`` when:
    - The user has no current module (curriculum complete).
    - The current module has no incomplete listening lessons.
    """
    listening_lesson = _find_next_listening_lesson(user_id, db)
    if listening_lesson is None:
        logger.debug("listening_slot user=%s no_listening_lesson skipped", user_id)
        return None

    completed = _listening_done_today(user_id, db)

    module = getattr(listening_lesson, 'module', None)
    level = getattr(module, 'level', None) if module is not None else None

    base_url = f'/learn/{listening_lesson.id}/?from=linear_plan'
    url = build_slot_url(f'/learn/{listening_lesson.id}/', LinearSlotKind.CURRICULUM)

    logger.info(
        "listening_slot user=%s lesson=%s type=%s module=%s state=%s",
        user_id, listening_lesson.id, listening_lesson.type,
        getattr(module, 'number', None),
        'done_today' if completed else 'pending',
    )
    return LinearSlot(
        kind='listening',
        title=listening_lesson.title,
        lesson_type=listening_lesson.type,
        eta_minutes=_eta_minutes(listening_lesson.type) or _LISTENING_SLOT_ETA_MINUTES,
        url=url,
        completed=completed,
        data={
            'lesson_id': listening_lesson.id,
            'lesson_title': listening_lesson.title,
            'lesson_type': listening_lesson.type,
            'estimated_minutes': _LISTENING_SLOT_ETA_MINUTES,
            'module_id': getattr(listening_lesson, 'module_id', None),
            'module_number': getattr(module, 'number', None),
            'level_code': getattr(level, 'code', None) if level is not None else None,
        },
    )
