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

from sqlalchemy import and_, func, or_

from app.curriculum.constants import PASSING_SCORE_DEFAULT, PASSING_SCORE_DICTATION
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

# Lesson types whose completion requires a passing score. Activity-based
# types (vocabulary, reading, flashcards, etc.) have no meaningful score
# threshold — the fallback LessonProgress check should pass them through.
_SCORE_BASED_LESSON_TYPES: frozenset[str] = frozenset({
    'quiz', 'grammar', 'final_test',
    'listening_quiz', 'dialogue_completion_quiz',
    'ordering_quiz', 'translation_quiz', 'listening_immersion_quiz',
    'matching', 'translation', 'sentence_correction',
    'sentence_completion', 'collocation_matching', 'dictation', 'audio_fill_blank',
})

_ADAPTIVE_LOW_THRESHOLD = 60.0
_ADAPTIVE_HIGH_THRESHOLD = 90.0
_ADAPTIVE_HINT_WINDOW = 5


def _lesson_meets_passing(lesson: Any, score: Optional[float]) -> bool:
    """True when a completed lesson counts as *done today*.

    Completion-only types always count; score-based types must have met their
    REAL per-lesson passing threshold via ``get_lesson_passing_score`` — which
    honors a content ``passing_score_percent`` override (audit E-043). Doing
    this in Python guarantees consistency with the canonical resolver instead
    of re-deriving thresholds (and the dictation=80 default) in SQL. Previously
    a hardcoded 70 floor re-offered a lesson with a lower content threshold
    (passed at 55 vs bar 50) whenever its XP StreakEvent didn't land.
    """
    from app.curriculum.constants import get_lesson_passing_score
    if (getattr(lesson, 'type', '') or '') not in _SCORE_BASED_LESSON_TYPES:
        return True
    return (score or 0) >= get_lesson_passing_score(lesson)


def _eta_minutes(lesson_type: Optional[str]) -> int:
    return _LESSON_ETA_MINUTES.get(lesson_type or '', _DEFAULT_ETA_MINUTES)


def _curriculum_done_today(user_id: int, db: Any) -> bool:
    """Return True when the user has completed a curriculum lesson today.

    Primary: StreakEvent(xp_linear) from ``maybe_award_curriculum_xp``.
    Fallback: any LessonProgress(completed) inside the user-local day —
    catches paths where XP failed but the lesson was still marked done.
    """
    from app.achievements.models import StreakEvent

    today = get_linear_event_local_date(user_id, db)
    xp_exists = db.session.query(
        db.session.query(StreakEvent)
        .filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.event_date == today,
            StreakEvent.details['source'].astext.in_(list(_CURRICULUM_XP_SOURCES)),
        )
        .exists()
    ).scalar() or False
    if xp_exists:
        return True

    today_start, today_end = get_user_local_day_bounds(user_id, db)
    rows = (
        db.session.query(LessonProgress.score, Lessons)
        .join(Lessons, Lessons.id == LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            LessonProgress.completed_at.isnot(None),
            LessonProgress.completed_at >= today_start,
            LessonProgress.completed_at < today_end,
            Lessons.type.in_(tuple(_CURRICULUM_LESSON_TYPES)),
        )
        .all()
    )
    return any(_lesson_meets_passing(lesson, score) for score, lesson in rows)


def _get_lesson_completed_today(user_id: int, db: Any) -> Optional[Lessons]:
    """Return the FIRST curriculum lesson finished today.

    Anchoring on the *first* completion (not the most recent) keeps the
    required-curriculum card stable as the user goes on to complete more
    lessons via the optional section. Without this anchor, the required
    card would jump to whichever lesson was completed last, and previously
    completed lessons would silently disappear from the plan.

    Primary signal: today's earliest ``StreakEvent.details['lesson_id']``
    from ``maybe_award_curriculum_xp``. Fallback: ``LessonProgress``.
    """
    lessons = get_curriculum_lessons_completed_today(user_id, db)
    return lessons[0] if lessons else None


def get_curriculum_lessons_completed_today(
    user_id: int,
    db: Any,
    exclude_lesson_ids: Optional[set[int]] = None,
) -> list[Lessons]:
    """Return curriculum lessons completed today, in completion order.

    Used by the optional-section orchestrator to surface accumulated
    completed cards under the required-curriculum card — so a user who
    finishes the required lesson and keeps going through optional lessons
    sees each completed lesson stay visible instead of being replaced by
    the next pending lesson.

    Combines ``StreakEvent`` (primary, carries ``lesson_id``) with
    ``LessonProgress`` (fallback). ``exclude_lesson_ids`` lets the caller
    skip a lesson already rendered elsewhere (e.g. the one anchored in
    required) so it does not appear twice.
    """
    from app.achievements.models import StreakEvent

    excluded: set[int] = set(exclude_lesson_ids or ())

    today = get_linear_event_local_date(user_id, db)
    ordered_ids: list[int] = []
    seen_ids: set[int] = set()

    events = (
        db.session.query(StreakEvent)
        .filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.event_date == today,
            StreakEvent.details['source'].astext.in_(list(_CURRICULUM_XP_SOURCES)),
        )
        .order_by(StreakEvent.id.asc())
        .all()
    )
    for event in events:
        lesson_id_raw = (event.details or {}).get('lesson_id')
        if lesson_id_raw is None:
            continue
        try:
            lesson_id = int(lesson_id_raw)
        except (TypeError, ValueError):
            continue
        if lesson_id in excluded or lesson_id in seen_ids:
            continue
        seen_ids.add(lesson_id)
        ordered_ids.append(lesson_id)

    today_start, today_end = get_user_local_day_bounds(user_id, db)
    fallback_rows = (
        db.session.query(LessonProgress.lesson_id, LessonProgress.score, Lessons)
        .join(Lessons, Lessons.id == LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            LessonProgress.completed_at.isnot(None),
            LessonProgress.completed_at >= today_start,
            LessonProgress.completed_at < today_end,
            Lessons.type.in_(tuple(_CURRICULUM_LESSON_TYPES)),
        )
        .order_by(LessonProgress.completed_at.asc())
        .all()
    )
    for lesson_id, score, lesson in fallback_rows:
        if lesson_id in excluded or lesson_id in seen_ids:
            continue
        if not _lesson_meets_passing(lesson, score):  # honor per-lesson bar (E-043)
            continue
        seen_ids.add(lesson_id)
        ordered_ids.append(lesson_id)

    if not ordered_ids:
        return []

    rows = (
        db.session.query(Lessons)
        .filter(Lessons.id.in_(ordered_ids))
        .all()
    )
    by_id = {row.id: row for row in rows}
    return [by_id[lid] for lid in ordered_ids if lid in by_id]


def build_curriculum_completed_item(
    lesson: Lessons,
    *,
    section: str = 'optional',
) -> PlanItem:
    """Build a PlanItem for a curriculum lesson already completed today."""
    module = lesson.module
    level = module.level if module is not None else None
    return PlanItem(
        id=f'curriculum:lesson:{lesson.id}',
        section=section,  # type: ignore[arg-type]
        kind='curriculum',
        title=lesson.title,
        subtitle=_lesson_subtitle(lesson),
        lesson_type=lesson.type,
        eta_minutes=0,
        url=None,
        completed=True,
        completion_signal='lesson_completed',
        data={
            'lesson_id': lesson.id,
            'lesson_number': lesson.number,
            'module_id': lesson.module_id,
            'module_number': module.number if module is not None else None,
            'module_title': module.title if module is not None else None,
            'level_code': level.code if level is not None else None,
            'state': 'done_today',
        },
    )


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
    from app.curriculum.routes.public import PUBLIC_CEFR_CODES
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
        .filter(
            UserGrammarExercise.user_id == user_id,
            # Public CEFR levels only — match the sibling grammar-SRS consumers
            # so a non-public/draft topic can't surface as a weak hint (E-042).
            GrammarTopic.level.in_(PUBLIC_CEFR_CODES),
        )
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

    # Union curriculum grammar accuracy. Course grammar lessons write
    # LessonAttempt (correct_answers/total_questions, including failed attempts),
    # not UserGrammarExercise — without this the weak hint is blind to the
    # spine's own grammar work. A topic already flagged weak by standalone
    # practice keeps that accuracy (don't overwrite).
    from app.curriculum.models import LessonAttempt

    c_correct = func.sum(LessonAttempt.correct_answers)
    c_total = func.sum(LessonAttempt.total_questions)
    c_rows = (
        db.session.query(
            GrammarTopic.id,
            GrammarTopic.title,
            c_correct.label('correct'),
            c_total.label('total'),
        )
        .join(Lessons, Lessons.grammar_topic_id == GrammarTopic.id)
        .join(LessonAttempt, LessonAttempt.lesson_id == Lessons.id)
        .filter(
            LessonAttempt.user_id == user_id,
            Lessons.type == 'grammar',
            GrammarTopic.level.in_(PUBLIC_CEFR_CODES),  # public levels only (E-042)
        )
        .group_by(GrammarTopic.id, GrammarTopic.title)
        .having(c_total >= min_attempts)
        .all()
    )
    for row in c_rows:
        tid = int(row.id)
        if tid in result:
            continue
        total = int(row.total or 0)
        if total <= 0:
            continue
        accuracy = float(row.correct or 0) / total
        if accuracy < max_accuracy:
            result[tid] = {'title': row.title, 'accuracy': round(accuracy, 3)}
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
    exclude_lesson_ids: Optional[set[int]] = None,
) -> Optional[PlanItem]:
    """Return the curriculum PlanItem or None if no eligible lesson exists.

    The orchestrator passes ``section`` to mark required vs optional. If
    ``next_lesson is None`` the builder returns None — the orchestrator is
    responsible for adding ``setup_level`` (no history) or emitting a
    ``course_completed`` milestone (has history) instead.

    ``exclude_lesson_ids`` is forwarded to ``find_next_lesson_linear`` so the
    optional builder can skip the lesson already shown in required.
    """
    if next_lesson is None:
        next_lesson = find_next_lesson_linear(user_id, db, exclude_lesson_ids=exclude_lesson_ids)

    # Required slot anchors on the FIRST lesson completed today even when no
    # pending lesson remains (e.g. user has finished every available lesson).
    # Without this, the required curriculum card would silently disappear and
    # the completed-today lesson would land in the optional section instead,
    # confusing the day-summary («что я сегодня прошёл?»).
    done_today = _curriculum_done_today(user_id, db)
    if done_today and section == 'required':
        completed_lesson = _get_lesson_completed_today(user_id, db) or next_lesson
        if completed_lesson is None:
            # Defensive: done_today should imply a completed lesson exists.
            return None
        c_module = completed_lesson.module
        c_level = c_module.level if c_module is not None else None
        return PlanItem(
            id=f'curriculum:lesson:{completed_lesson.id}',
            section=section,  # type: ignore[arg-type]
            kind='curriculum',
            title=completed_lesson.title,
            subtitle=_lesson_subtitle(completed_lesson),
            lesson_type=completed_lesson.type,
            eta_minutes=0,
            url=None,
            completed=True,
            completion_signal='lesson_completed',
            data={
                'lesson_id': completed_lesson.id,
                'lesson_number': completed_lesson.number,
                'module_id': completed_lesson.module_id,
                'module_number': c_module.number if c_module is not None else None,
                'module_title': c_module.title if c_module is not None else None,
                'level_code': c_level.code if c_level is not None else None,
                'state': 'done_today',
            },
        )

    if next_lesson is None:
        return None

    # Guard for optional section: if done_today and the resolved next_lesson
    # is the same as today's completed lesson (stale-state edge case), return
    # None to prevent a phantom duplicate in the optional block.
    if done_today and section == 'optional':
        completed_lesson = _get_lesson_completed_today(user_id, db)
        if completed_lesson is not None and next_lesson.id == completed_lesson.id:
            return None

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
