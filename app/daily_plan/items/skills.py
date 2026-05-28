"""Skill-lesson item builders (listening, speaking, writing).

Each builder surfaces the next incomplete skill-type lesson within the
user's current curriculum module. Returns None when there is no eligible
lesson — the orchestrator skips the section accordingly.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from app.curriculum.models import LessonProgress, Lessons
from app.daily_plan.items import PlanItem
from app.daily_plan.items.curriculum import _eta_minutes
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.progression import find_next_lesson_linear

logger = logging.getLogger(__name__)

_LISTENING_LESSON_TYPES: frozenset[str] = frozenset({
    'listening_immersion', 'listening_immersion_quiz',
    'dictation', 'audio_fill_blank',
})
_LISTENING_XP_SOURCES: frozenset[str] = frozenset({
    'linear_curriculum_listening_immersion',
    'linear_curriculum_dictation',
    'linear_curriculum_audio_fill_blank',
    'linear_listening',
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

    "Respecting ordering" means we never offer a skill lesson that sits
    ahead of the spine's current position — otherwise the user would be
    handed e.g. lesson 7 (listening) when they're still on lesson 5
    (sentence_completion), and the lesson-access decorator would block
    them with "complete previous lessons first". The unified plan goal
    is sequential progression: SRS → curriculum lesson 4 → reading →
    curriculum lesson 5 → ..., not random skill picks out of order.

    Concretely: the candidate's ``number`` must be ``<= next_lesson.number``.
    When the spine's next lesson is itself a skill type, the curriculum
    slot already offers it and the orchestrator dedup eliminates duplicates.
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
            # Only offer a skill lesson that the spine has already reached —
            # i.e. it sits at or before the next-incomplete spine position.
            Lessons.number <= next_lesson.number,
        )
        .order_by(Lessons.number.asc(), Lessons.id.asc())
        .first()
    )


def _xp_source_done_today(user_id: int, db: Any, sources: Iterable[str]) -> bool:
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date

    today = get_linear_event_local_date(user_id, db)
    query = db.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.event_date == today,
        StreakEvent.details['source'].astext.in_(list(sources)),
    )
    return db.session.query(query.exists()).scalar() or False


def _lesson_progress_done_today(user_id: int, db: Any, lesson_types: Iterable[str]) -> bool:
    from app.utils.time_utils import get_user_local_day_bounds

    today_start, _ = get_user_local_day_bounds(user_id, db)
    return (
        db.session.query(LessonProgress)
        .join(Lessons, LessonProgress.lesson_id == Lessons.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            LessonProgress.completed_at >= today_start,
            Lessons.type.in_(list(lesson_types)),
        )
        .first() is not None
    )


def _writing_done_today(user_id: int, db: Any) -> bool:
    from app.curriculum.models import LessonAttempt, UserWritingAttempt
    from app.utils.time_utils import get_user_local_day_bounds

    today_start, _ = get_user_local_day_bounds(user_id, db)
    if (
        db.session.query(UserWritingAttempt.id)
        .filter(
            UserWritingAttempt.user_id == user_id,
            UserWritingAttempt.created_at >= today_start,
        )
        .first() is not None
    ):
        return True

    return (
        db.session.query(LessonAttempt.id)
        .join(Lessons, Lessons.id == LessonAttempt.lesson_id)
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.passed.is_(True),
            LessonAttempt.completed_at >= today_start,
            Lessons.type.in_(list(_WRITING_LESSON_TYPES)),
        )
        .first() is not None
    )


def _build_done_placeholder(
    *, kind: str, section: str, title: str, completion_signal: str,
) -> PlanItem:
    """Build a generic «done today» card for a skill kind without a pending lesson."""
    return PlanItem(
        id=f'{kind}:done-today',
        section=section,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        title=title,
        subtitle='на сегодня всё',
        lesson_type=None,
        eta_minutes=0,
        url=None,
        completed=True,
        completion_signal=completion_signal,  # type: ignore[arg-type]
        data={'done_placeholder': True},
    )


def _build_skill_item(
    user_id: int,
    db: Any,
    *,
    section: str,
    kind: str,
    lesson: Lessons,
    completed: bool,
    completion_signal: str,
    extra_data: Optional[dict[str, Any]] = None,
) -> PlanItem:
    module = getattr(lesson, 'module', None)
    level = getattr(module, 'level', None) if module is not None else None
    data: dict[str, Any] = {
        'lesson_id': lesson.id,
        'lesson_title': lesson.title,
        'lesson_type': lesson.type,
        'module_id': getattr(lesson, 'module_id', None),
        'module_number': getattr(module, 'number', None),
        'level_code': getattr(level, 'code', None) if level is not None else None,
    }
    if extra_data:
        data.update(extra_data)

    slot_kind_map = {
        'listening': LinearSlotKind.LISTENING,
        'speaking': LinearSlotKind.SPEAKING,
        'writing': LinearSlotKind.WRITING,
    }
    url = build_slot_url(f'/learn/{lesson.id}/', slot_kind_map[kind])

    return PlanItem(
        id=f'{kind}:lesson:{lesson.id}',
        section=section,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        title=lesson.title,
        subtitle=None,
        lesson_type=lesson.type,
        eta_minutes=_eta_minutes(lesson.type),
        url=url,
        completed=completed,
        completion_signal=completion_signal,  # type: ignore[arg-type]
        data=data,
    )


def build_listening_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'optional',
) -> Optional[PlanItem]:
    lesson = _find_next_skill_lesson(user_id, db, _LISTENING_LESSON_TYPES)
    if lesson is None:
        # Done-today placeholder only in required so the counter reflects
        # progress; in optional the bonus list stays actionable.
        if section == 'required' and _xp_source_done_today(user_id, db, _LISTENING_XP_SOURCES):
            return _build_done_placeholder(kind='listening', section=section,
                                           title='Аудирование выполнено сегодня',
                                           completion_signal='listening_attempt')
        return None
    completed = _xp_source_done_today(user_id, db, _LISTENING_XP_SOURCES)
    return _build_skill_item(
        user_id, db,
        section=section, kind='listening', lesson=lesson,
        completed=completed, completion_signal='listening_attempt',
    )


def build_speaking_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'optional',
) -> Optional[PlanItem]:
    lesson = _find_next_skill_lesson(user_id, db, _SPEAKING_LESSON_TYPES)
    if lesson is None:
        if section == 'required' and _lesson_progress_done_today(user_id, db, _SPEAKING_LESSON_TYPES):
            return _build_done_placeholder(kind='speaking', section=section,
                                           title='Произношение выполнено сегодня',
                                           completion_signal='pronunciation_attempt')
        return None
    completed = _lesson_progress_done_today(user_id, db, _SPEAKING_LESSON_TYPES)
    speech_api_required = lesson.type in _SPEECH_API_LESSON_TYPES
    return _build_skill_item(
        user_id, db,
        section=section, kind='speaking', lesson=lesson,
        completed=completed, completion_signal='pronunciation_attempt',
        extra_data={'speech_api_required': speech_api_required},
    )


def build_writing_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'optional',
) -> Optional[PlanItem]:
    lesson = _find_next_skill_lesson(user_id, db, _WRITING_LESSON_TYPES)
    if lesson is None:
        if section == 'required' and _writing_done_today(user_id, db):
            return _build_done_placeholder(kind='writing', section=section,
                                           title='Письмо выполнено сегодня',
                                           completion_signal='writing_attempt')
        return None
    completed = _writing_done_today(user_id, db)
    prompt_preview: Optional[str] = None
    content = getattr(lesson, 'content', None) or {}
    if lesson.type == 'writing_prompt':
        prompt_preview = (content.get('prompt') or '')[:80] or None
    elif lesson.type == 'translation':
        prompt_preview = (content.get('russian') or '')[:80] or None
    extra: dict[str, Any] = {}
    if prompt_preview:
        extra['prompt_preview'] = prompt_preview
    return _build_skill_item(
        user_id, db,
        section=section, kind='writing', lesson=lesson,
        completed=completed, completion_signal='writing_attempt',
        extra_data=extra,
    )
