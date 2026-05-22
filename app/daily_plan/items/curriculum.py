"""Curriculum item builder for the unified daily plan.

Returns a ``PlanItem`` describing the next incomplete lesson on the linear
curriculum spine. Mirrors ``app/daily_plan/linear/slots/curriculum_slot.py``
but emits a PlanItem and **never** invents a fake «curriculum complete» or
«empty catalogue» card — those states are surfaced as milestone notifications
(genuine completion) or as setup items (no eligible content), handled by the
plan orchestrator.

When ``find_next_lesson_linear`` returns None, this builder returns None.
The orchestrator decides whether to add a ``setup_level`` item or emit a
``course_completed`` milestone.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func

from app.curriculum.models import LessonProgress, Lessons
from app.daily_plan.items import PlanItem
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.daily_plan.linear.xp import (
    LESSON_TYPE_TO_SOURCE,
    LINEAR_XP_EVENT_TYPE,
    get_linear_event_local_date,
)
from app.utils.time_utils import get_user_local_day_bounds

logger = logging.getLogger(__name__)

_CURRICULUM_XP_SOURCES: frozenset[str] = frozenset(LESSON_TYPE_TO_SOURCE.values())
_CURRICULUM_LESSON_TYPES: frozenset[str] = frozenset(LESSON_TYPE_TO_SOURCE)

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

_CARD_LESSON_TYPES = frozenset({'card', 'flashcards'})

_WEAK_ACCURACY_MAX = 0.6
_WEAK_MIN_ATTEMPTS = 3

_QUIZ_LESSON_TYPES: frozenset[str] = frozenset({
    'quiz', 'grammar', 'final_test',
    'listening_quiz', 'dialogue_completion_quiz',
    'ordering_quiz', 'translation_quiz', 'listening_immersion_quiz',
})
_ADAPTIVE_LOW_THRESHOLD = 60.0
_ADAPTIVE_HIGH_THRESHOLD = 90.0
_ADAPTIVE_HINT_WINDOW = 5


def _eta_minutes(lesson_type: Optional[str]) -> int:
    return _LESSON_ETA_MINUTES.get(lesson_type or '', _DEFAULT_ETA_MINUTES)


def _curriculum_done_today(user_id: int, db: Any) -> bool:
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


def _get_recent_quiz_scores(user_id: int, db: Any, n: int = _ADAPTIVE_HINT_WINDOW) -> list[float]:
    from app.curriculum.models import LessonAttempt

    rows = (
        db.session.query(LessonAttempt.score)
        .join(Lessons, Lessons.id == LessonAttempt.lesson_id)
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.score.isnot(None),
            LessonAttempt.completed_at.isnot(None),
            Lessons.type.in_(tuple(_QUIZ_LESSON_TYPES)),
        )
        .order_by(LessonAttempt.completed_at.desc())
        .limit(n)
        .all()
    )
    return [float(row.score) for row in rows]


def _compute_adaptive_hint(scores: list[float]) -> Optional[str]:
    if len(scores) < _ADAPTIVE_HINT_WINDOW:
        return None
    if all(s < _ADAPTIVE_LOW_THRESHOLD for s in scores):
        return 'слишком сложно'
    if all(s > _ADAPTIVE_HIGH_THRESHOLD for s in scores):
        return 'отлично, можно ускорить'
    return None


def _get_weak_grammar_topic_ids(
    user_id: int,
    db: Any,
    *,
    min_attempts: int = _WEAK_MIN_ATTEMPTS,
    max_accuracy: float = _WEAK_ACCURACY_MAX,
) -> dict[int, dict[str, Any]]:
    from app.grammar_lab.models import (
        GrammarExercise,
        GrammarTopic,
        UserGrammarExercise,
    )

    correct_sum = func.sum(UserGrammarExercise.correct_count)
    total_sum = func.sum(
        UserGrammarExercise.correct_count + UserGrammarExercise.incorrect_count
    )

    rows = (
        db.session.query(
            GrammarTopic.id,
            GrammarTopic.title,
            correct_sum.label('correct'),
            total_sum.label('total'),
        )
        .join(GrammarExercise, GrammarExercise.topic_id == GrammarTopic.id)
        .join(UserGrammarExercise, UserGrammarExercise.exercise_id == GrammarExercise.id)
        .filter(UserGrammarExercise.user_id == user_id)
        .group_by(GrammarTopic.id, GrammarTopic.title)
        .having(total_sum >= min_attempts)
        .all()
    )

    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        total = int(row.total or 0)
        if total <= 0:
            continue
        accuracy = float(row.correct or 0) / total
        if accuracy < max_accuracy:
            result[int(row.id)] = {'title': row.title, 'accuracy': round(accuracy, 3)}
    return result


def _lesson_grammar_topic_ids(lesson: Lessons) -> list[int]:
    direct = getattr(lesson, 'grammar_topic_id', None)
    return [int(direct)] if direct else []


def has_completed_history(user_id: int, db: Any) -> bool:
    """Return True if the user has ever completed any curriculum lesson.

    Used by the plan orchestrator to disambiguate ``next_lesson is None``
    between «genuinely course-complete» (emit milestone) and «no eligible
    content» (emit setup_level).
    """
    return (
        db.session.query(LessonProgress.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        )
        .first()
    ) is not None


def build_curriculum_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'required',
    next_lesson: Optional[Lessons] = None,
) -> Optional[PlanItem]:
    """Return the curriculum PlanItem or None if no eligible lesson exists.

    The orchestrator passes ``section`` to mark required vs optional. If
    ``next_lesson is None`` the builder returns None — the orchestrator is
    responsible for adding ``setup_level`` (no history) or emitting a
    ``course_completed`` milestone (has history) instead.
    """
    if next_lesson is None:
        next_lesson = find_next_lesson_linear(user_id, db)
    if next_lesson is None:
        return None

    # Always surface the next pending lesson on the spine. Previously this
    # branch returned today's completed lesson as a «done» card, which hid
    # the actual next step from the user (e.g. user finished L1 today, but
    # the card kept showing L1 instead of advancing to L2/L3).
    module = next_lesson.module
    level = module.level if module is not None else None
    data: dict[str, Any] = {
        'lesson_id': next_lesson.id,
        'lesson_number': next_lesson.number,
        'module_id': next_lesson.module_id,
        'module_number': module.number if module is not None else None,
        'module_title': module.title if module is not None else None,
        'level_code': level.code if level is not None else None,
    }

    weak_topics = _get_weak_grammar_topic_ids(user_id, db)
    if weak_topics:
        for tid in _lesson_grammar_topic_ids(next_lesson):
            info = weak_topics.get(tid)
            if info is not None:
                data['weak_topic_hint'] = True
                data['weak_topic_id'] = tid
                data['weak_topic_name'] = info['title']
                data['weak_topic_accuracy'] = info['accuracy']
                break

    adaptive_hint = _compute_adaptive_hint(_get_recent_quiz_scores(user_id, db))
    if adaptive_hint:
        data['adaptive_hint'] = adaptive_hint

    return PlanItem(
        id=f'curriculum:lesson:{next_lesson.id}',
        section=section,  # type: ignore[arg-type]
        kind='curriculum',
        title=next_lesson.title,
        subtitle=_lesson_subtitle(next_lesson),
        lesson_type=next_lesson.type,
        eta_minutes=_eta_minutes(next_lesson.type),
        url=_lesson_url(next_lesson),
        completed=False,
        completion_signal='lesson_completed',
        data=data,
    )


def _lesson_subtitle(lesson: Lessons) -> Optional[str]:
    module = lesson.module
    level = module.level if module is not None else None
    parts: list[str] = []
    if level is not None and getattr(level, 'code', None):
        parts.append(level.code)
    if module is not None and getattr(module, 'number', None) is not None:
        parts.append(f'M{module.number}')
    if getattr(lesson, 'number', None) is not None:
        parts.append(f'L{lesson.number}')
    return ' · '.join(parts) if parts else None
