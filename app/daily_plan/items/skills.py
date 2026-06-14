"""Skill-lesson type constants and spine-aware lookup helper.

The previous skill-slot builders (``build_listening_item`` etc.) and the
``done-today`` placeholder were removed: they piggybacked on the
curriculum slot when the spine's next lesson was itself a skill type,
which double-closed required slots and double-paid XP. Skill XP awards
(``maybe_award_listening_xp`` and friends) remain as bonus XP for any
matching activity, but no longer gate the day.

What stayed is the bare minimum needed by the challenge-item builder
(``app/daily_plan/items/challenge.py``) to resolve a listening lesson
URL for the ``listening_deep`` category — the helper is still useful
outside the daily-plan slot context.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from app.curriculum.models import LessonProgress, Lessons
from app.daily_plan.linear.progression import find_next_lesson_linear

logger = logging.getLogger(__name__)

_LISTENING_LESSON_TYPES: frozenset[str] = frozenset({
    'listening_immersion', 'listening_immersion_quiz',
    'dictation', 'audio_fill_blank',
})

_SPEAKING_LESSON_TYPES: frozenset[str] = frozenset({'pronunciation', 'shadow_reading'})
_SPEECH_API_LESSON_TYPES: frozenset[str] = frozenset({'pronunciation'})

_WRITING_LESSON_TYPES: frozenset[str] = frozenset({
    'writing_prompt', 'translation', 'sentence_correction',
})


def _find_next_skill_lesson(
    user_id: int,
    db: Any,
    lesson_types: Iterable[str],
) -> Optional[Lessons]:
    """Return the next incomplete skill lesson within the user's current
    module, respecting linear ordering on the spine.

    The candidate's ``number`` must be ``<= next_lesson.number`` so a
    spine-blocked skill lesson is never surfaced; the lesson-access
    decorator would 403 the click otherwise.
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
            Lessons.type.in_(list(lesson_types)),
            Lessons.id.notin_(db.session.query(completed_subq.c.lesson_id)),
            Lessons.number <= next_lesson.number,
        )
        .order_by(Lessons.number.asc(), Lessons.id.asc())
        .first()
    )
