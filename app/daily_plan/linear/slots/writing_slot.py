"""Writing extension slot for the linear daily plan.

Surfaces the next incomplete writing_prompt or translation lesson
in the user's current curriculum module as an optional extension slot.
Returns ``None`` when no eligible lesson is available — the chain
builder skips it silently.

Completion is keyed on whether the user submitted a UserWritingAttempt
today (writing_prompt) or has a completed LessonProgress for the lesson
(translation).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from app.curriculum.models import LessonProgress, Lessons
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.curriculum_slot import _eta_minutes

logger = logging.getLogger(__name__)

_WRITING_LESSON_TYPES: frozenset[str] = frozenset({
    'writing_prompt',
    'translation',
})

_WRITING_SLOT_ETA_MINUTES = 8


def _writing_done_today(user_id: int, lesson_id: int, db: Any) -> bool:
    """Return True when the user has done writing activity today.

    For writing_prompt lessons: any UserWritingAttempt submitted today counts.
    For translation and other types: falls back to LessonProgress completed.
    """
    from app.curriculum.models import UserWritingAttempt

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    has_attempt = (
        db.session.query(UserWritingAttempt.id)
        .filter(
            UserWritingAttempt.user_id == user_id,
            UserWritingAttempt.created_at >= today_start,
        )
        .first() is not None
    )
    if has_attempt:
        return True

    prog = (
        db.session.query(LessonProgress)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.lesson_id == lesson_id,
            LessonProgress.status == 'completed',
        )
        .first()
    )
    return prog is not None


def _find_next_writing_lesson(user_id: int, db: Any) -> Optional[Lessons]:
    """Return the next incomplete writing lesson in the user's current module.

    Looks within the module of the user's current spine position. Returns
    ``None`` when the current module has no incomplete writing lessons.
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
            Lessons.type.in_(list(_WRITING_LESSON_TYPES)),
            Lessons.id.notin_(db.session.query(completed_subq.c.lesson_id)),
        )
        .order_by(Lessons.number.asc(), Lessons.id.asc())
        .first()
    )


def build_writing_slot(user_id: int, db: Any) -> Optional[LinearSlot]:
    """Build the writing extension slot.

    Returns ``None`` when:
    - The user has no current module (curriculum complete).
    - The current module has no incomplete writing lessons.
    """
    writing_lesson = _find_next_writing_lesson(user_id, db)
    if writing_lesson is None:
        logger.debug("writing_slot user=%s no_writing_lesson skipped", user_id)
        return None

    completed = _writing_done_today(user_id, writing_lesson.id, db)

    module = getattr(writing_lesson, 'module', None)
    level = getattr(module, 'level', None) if module is not None else None

    url = build_slot_url(f'/learn/{writing_lesson.id}/', LinearSlotKind.CURRICULUM)

    prompt_preview: Optional[str] = None
    content = getattr(writing_lesson, 'content', None) or {}
    if writing_lesson.type == 'writing_prompt':
        prompt_preview = (content.get('prompt') or '')[:80] or None
    elif writing_lesson.type == 'translation':
        prompt_preview = (content.get('russian') or '')[:80] or None

    logger.info(
        "writing_slot user=%s lesson=%s type=%s module=%s state=%s",
        user_id, writing_lesson.id, writing_lesson.type,
        getattr(module, 'number', None),
        'done_today' if completed else 'pending',
    )
    return LinearSlot(
        kind='writing',
        title=writing_lesson.title,
        lesson_type=writing_lesson.type,
        eta_minutes=_eta_minutes(writing_lesson.type) or _WRITING_SLOT_ETA_MINUTES,
        url=url,
        completed=completed,
        data={
            'lesson_id': writing_lesson.id,
            'lesson_title': writing_lesson.title,
            'lesson_type': writing_lesson.type,
            'estimated_minutes': _WRITING_SLOT_ETA_MINUTES,
            'prompt_preview': prompt_preview,
            'module_id': getattr(writing_lesson, 'module_id', None),
            'module_number': getattr(module, 'number', None),
            'level_code': getattr(level, 'code', None) if level is not None else None,
        },
    )
