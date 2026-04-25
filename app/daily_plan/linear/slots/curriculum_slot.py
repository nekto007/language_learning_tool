"""Curriculum lesson slot — first baseline slot on the linear spine.

Returns a ``LinearSlot`` pointing at the next incomplete lesson on the
curriculum spine. URL is the unified learn entry (``/learn/{lesson_id}/``)
with ``?from=linear_plan`` so downstream endpoints can detect the source.
Task 5 will extend the card-lesson flow with an extra ``source`` param
for SRS budget handling; this slot stays source-agnostic.
"""
from __future__ import annotations

from typing import Any, Optional

from app.curriculum.models import LessonProgress, Lessons
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.xp import (
    LESSON_TYPE_TO_SOURCE,
    LINEAR_XP_EVENT_TYPE,
    get_linear_event_local_date,
)
from app.utils.time_utils import get_user_local_day_bounds

# All XP source keys that belong to a curriculum lesson completion.
_CURRICULUM_XP_SOURCES: frozenset[str] = frozenset(LESSON_TYPE_TO_SOURCE.values())
_CURRICULUM_LESSON_TYPES: frozenset[str] = frozenset(LESSON_TYPE_TO_SOURCE)

# ETA estimates for each of the 12 curriculum lesson types plus legacy
# aliases that still appear in content (matching/text/flashcards).
_LESSON_ETA_MINUTES: dict[str, int] = {
    'vocabulary': 8,
    'card': 10,
    'grammar': 12,
    'quiz': 6,
    'reading': 10,
    'listening_quiz': 8,
    'dialogue_completion_quiz': 8,
    'ordering_quiz': 6,
    'translation_quiz': 8,
    'listening_immersion': 12,
    'listening_immersion_quiz': 8,
    'final_test': 15,
    'matching': 5,
    'text': 15,
    'flashcards': 8,
}

_DEFAULT_ETA_MINUTES = 10

# Lesson types that get an extra ``source=linear_plan_card`` query param on
# their URL so the card-lesson controller can enable SRS budget mixing
# (see ``app/curriculum/routes/card_lessons.py``).
_CARD_LESSON_TYPES = frozenset({'card', 'flashcards'})


def _eta_minutes(lesson_type: Optional[str]) -> int:
    return _LESSON_ETA_MINUTES.get(lesson_type or '', _DEFAULT_ETA_MINUTES)


def _curriculum_done_today(user_id: int, db: Any) -> bool:
    """Return True when the user has already earned curriculum XP today."""
    from app.achievements.models import StreakEvent

    today = get_linear_event_local_date(user_id, db)
    query = db.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.event_date == today,
        StreakEvent.details['source'].astext.in_(list(_CURRICULUM_XP_SOURCES)),
    )
    return db.session.query(query.exists()).scalar() or False


def _get_lesson_completed_today(user_id: int, db: Any) -> Optional[Lessons]:
    """Return the most recent linear-curriculum lesson completed today."""
    today_start, today_end = get_user_local_day_bounds(user_id, db)
    progress = (
        db.session.query(LessonProgress)
        .join(Lessons, Lessons.id == LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            LessonProgress.completed_at.isnot(None),
            LessonProgress.completed_at >= today_start,
            LessonProgress.completed_at < today_end,
            Lessons.type.in_(tuple(_CURRICULUM_LESSON_TYPES)),
        )
        .order_by(LessonProgress.completed_at.desc())
        .first()
    )
    if progress is None:
        return None
    return db.session.get(Lessons, progress.lesson_id)


def _lesson_url(lesson: Lessons) -> str:
    base = f'/learn/{lesson.id}/'
    if lesson.type in _CARD_LESSON_TYPES:
        base += '?source=linear_plan_card'
    return build_slot_url(base, LinearSlotKind.CURRICULUM)


def build_curriculum_slot(
    user_id: int,
    db: Any,
    next_lesson: Optional[Lessons] = None,
) -> LinearSlot:
    """Build the curriculum slot describing the next linear lesson.

    ``next_lesson`` may be passed in when the caller already resolved it
    (e.g., the plan assembler reuses it for position + continuation).
    When the user has completed the curriculum, returns a completed empty
    slot with no URL.
    """
    if next_lesson is None:
        next_lesson = find_next_lesson_linear(user_id, db)

    if next_lesson is None:
        return LinearSlot(
            kind='curriculum',
            title='Curriculum complete',
            lesson_type=None,
            eta_minutes=0,
            url=None,
            completed=True,
            data={},
        )

    # Authoritative completion: did the user earn curriculum XP today?
    # This is idempotent and decoupled from which lesson comes next,
    # so we avoid incorrectly marking the upcoming lesson as "done".
    done_today = _curriculum_done_today(user_id, db)

    if done_today:
        completed_lesson = _get_lesson_completed_today(user_id, db)
        if completed_lesson is None:
            return LinearSlot(
                kind='curriculum',
                title='Урок завершён',
                lesson_type=None,
                eta_minutes=0,
                url=None,
                completed=True,
                data={},
            )
        module = completed_lesson.module
        level = module.level if module is not None else None
        return LinearSlot(
            kind='curriculum',
            title=completed_lesson.title,
            lesson_type=completed_lesson.type,
            eta_minutes=0,
            url=None,
            completed=True,
            data={
                'lesson_id': completed_lesson.id,
                'lesson_number': completed_lesson.number,
                'module_id': completed_lesson.module_id,
                'module_number': module.number if module is not None else None,
                'level_code': level.code if level is not None else None,
            },
        )

    module = next_lesson.module
    level = module.level if module is not None else None

    return LinearSlot(
        kind='curriculum',
        title=next_lesson.title,
        lesson_type=next_lesson.type,
        eta_minutes=_eta_minutes(next_lesson.type),
        url=_lesson_url(next_lesson),
        completed=False,
        data={
            'lesson_id': next_lesson.id,
            'lesson_number': next_lesson.number,
            'module_id': next_lesson.module_id,
            'module_number': module.number if module is not None else None,
            'level_code': level.code if level is not None else None,
        },
    )
