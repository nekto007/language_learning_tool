"""Speaking extension slot for the linear daily plan.

Surfaces the next incomplete pronunciation or shadow_reading lesson
in the user's current curriculum module as an optional extension slot.
Returns ``None`` when no eligible lesson is available — the chain
builder skips it silently.

Completion is keyed on LessonProgress.completed for the lesson
(both pronunciation and shadow_reading write LessonProgress on submit).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.curriculum.models import LessonProgress, Lessons
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.curriculum_slot import _eta_minutes

logger = logging.getLogger(__name__)

_SPEAKING_LESSON_TYPES: frozenset[str] = frozenset({
    'pronunciation',
    'shadow_reading',
})

# pronunciation requires Web Speech API; shadow_reading does not
_SPEECH_API_LESSON_TYPES: frozenset[str] = frozenset({'pronunciation'})

_SPEAKING_SLOT_ETA_MINUTES = 7


def _speaking_done_today(user_id: int, db: Any) -> bool:
    """Return True when the user completed any speaking lesson today."""
    from app.utils.time_utils import get_user_local_day_bounds
    today_start, _ = get_user_local_day_bounds(user_id, db)
    return (
        db.session.query(LessonProgress)
        .join(Lessons, LessonProgress.lesson_id == Lessons.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            LessonProgress.completed_at >= today_start,
            Lessons.type.in_(list(_SPEAKING_LESSON_TYPES)),
        )
        .first() is not None
    )


def _find_next_speaking_lesson(user_id: int, db: Any) -> Optional[Lessons]:
    """Return the next incomplete speaking lesson in the user's current module.

    Looks within the module of the user's current spine position. Returns
    ``None`` when the current module has no incomplete speaking lessons.
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
            Lessons.type.in_(list(_SPEAKING_LESSON_TYPES)),
            Lessons.id.notin_(db.session.query(completed_subq.c.lesson_id)),
        )
        .order_by(Lessons.number.asc(), Lessons.id.asc())
        .first()
    )


def build_speaking_slot(user_id: int, db: Any) -> Optional[LinearSlot]:
    """Build the speaking extension slot.

    Returns ``None`` when:
    - The user has no current module (curriculum complete).
    - The current module has no incomplete speaking lessons.
    """
    speaking_lesson = _find_next_speaking_lesson(user_id, db)
    if speaking_lesson is None:
        logger.debug("speaking_slot user=%s no_speaking_lesson skipped", user_id)
        return None

    completed = _speaking_done_today(user_id, db)
    speech_api_required = speaking_lesson.type in _SPEECH_API_LESSON_TYPES

    module = getattr(speaking_lesson, 'module', None)
    level = getattr(module, 'level', None) if module is not None else None

    url = build_slot_url(f'/learn/{speaking_lesson.id}/', LinearSlotKind.CURRICULUM)

    logger.info(
        "speaking_slot user=%s lesson=%s type=%s module=%s speech_api=%s state=%s",
        user_id, speaking_lesson.id, speaking_lesson.type,
        getattr(module, 'number', None),
        speech_api_required,
        'done' if completed else 'pending',
    )
    return LinearSlot(
        kind='speaking',
        title=speaking_lesson.title,
        lesson_type=speaking_lesson.type,
        eta_minutes=_eta_minutes(speaking_lesson.type) or _SPEAKING_SLOT_ETA_MINUTES,
        url=url,
        completed=completed,
        data={
            'lesson_id': speaking_lesson.id,
            'lesson_title': speaking_lesson.title,
            'lesson_type': speaking_lesson.type,
            'estimated_minutes': _SPEAKING_SLOT_ETA_MINUTES,
            'speech_api_required': speech_api_required,
            'module_id': getattr(speaking_lesson, 'module_id', None),
            'module_number': getattr(module, 'number', None),
            'level_code': getattr(level, 'code', None) if level is not None else None,
        },
    )
