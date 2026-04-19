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
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.daily_plan.linear.slots import LinearSlot

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


def _eta_minutes(lesson_type: Optional[str]) -> int:
    return _LESSON_ETA_MINUTES.get(lesson_type or '', _DEFAULT_ETA_MINUTES)


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

    progress = (
        db.session.query(LessonProgress)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.lesson_id == next_lesson.id,
        )
        .first()
    )
    completed = bool(progress and progress.status == 'completed')

    module = next_lesson.module
    level = module.level if module is not None else None

    return LinearSlot(
        kind='curriculum',
        title=next_lesson.title,
        lesson_type=next_lesson.type,
        eta_minutes=_eta_minutes(next_lesson.type),
        url=f'/learn/{next_lesson.id}/?from=linear_plan',
        completed=completed,
        data={
            'lesson_id': next_lesson.id,
            'lesson_number': next_lesson.number,
            'module_id': next_lesson.module_id,
            'module_number': module.number if module is not None else None,
            'level_code': level.code if level is not None else None,
        },
    )
