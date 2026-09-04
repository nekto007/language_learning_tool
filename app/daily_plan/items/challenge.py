"""Daily challenge item builder for the unified daily plan.

Challenges live in ``optional`` only — they never gate ``day_secured``.
The challenge surfaces with its ``bonus_xp`` so the dashboard can render
the multiplier. ``data.is_challenge=True`` lets the UI style the card
distinctly (highlight, badge).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.challenge import (
    CHALLENGE_ACCURACY_MIN_SCORE,
    CHALLENGE_GRADED_LESSON_TYPES,
    CHALLENGE_SPEED_RUN_MAX_SECONDS,
)
from app.daily_plan.items import PlanItem
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url

logger = logging.getLogger(__name__)

_CHALLENGE_ETA_MINUTES = 7


def build_challenge_item(user_id: int, db: Any) -> Optional[PlanItem]:
    """Return today's daily-challenge PlanItem (completed or pending).

    Completed challenges are surfaced as a done card so the dashboard
    shows the user what they accomplished today, instead of hiding the
    section entirely. ``completed=True`` lets the template render the
    strike-through state.

    URL targets the specific lesson the challenge is bound to
    (``DailyChallenge.lesson_id``), with ``?from=linear_plan&slot=challenge``
    so the lesson page renders plan-aware CTAs after completion.
    """
    from app.daily_plan.challenge import get_today_challenge

    try:
        info = get_today_challenge(user_id, db)
    except Exception:  # pragma: no cover — challenge seeding is defensive
        logger.exception("challenge_item user=%s failed to load challenge", user_id)
        return None

    is_completed = bool(info.get('is_completed'))

    category = info.get('category') or 'speed_run'
    bonus_xp = int(info.get('bonus_xp') or 0)
    challenge_id = info.get('id')

    title_map = {
        'speed_run': 'Челлендж дня: пройди урок быстро',
        'accuracy_focus': 'Челлендж дня: целься в точность',
        'listening_deep': 'Челлендж дня: глубокое аудирование',
    }
    subtitle = f'+{bonus_xp} XP · сегодня' if bonus_xp else 'Бонус-задание дня'

    # Resolve a target the criteria can actually accept (DP-048):
    #   - listening_deep → the pinned ``DailyChallenge.lesson_id``, else the
    #     next listening lesson reachable on the spine. The criterion needs a
    #     ``ListeningAttempt``, which only dictation / audio_fill_blank write,
    #     so an arbitrary next lesson can never satisfy it.
    #   - speed_run / accuracy_focus → the next spine lesson when its type is
    #     server-graded; accuracy_focus may also fall back to the most recent
    #     passed graded lesson as a retake (``?retry=true`` — without it the
    #     completed lesson opens on its result screen, not a new attempt).
    #     speed_run has no retake path: ``LessonAttempt.started_at`` is copied
    #     from the progress row's first-open timestamp, so a retake can never
    #     fit the 5-minute window.
    # A pending challenge without a reachable target gets no card at all —
    # a card pointing at a lesson that cannot complete the challenge is the
    # bug, not the absence of the card. A completed challenge stays visible
    # regardless (the day's history), even when no target resolves any more.
    lesson_id = info.get('lesson_id')
    retry = False
    if lesson_id is None:
        try:
            lesson_id, retry = _resolve_target_lesson(user_id, db, category)
        except Exception:
            logger.exception("challenge_item user=%s lesson resolution failed", user_id)
            lesson_id = None
    if lesson_id is None and not is_completed:
        return None

    if not is_completed and category == 'accuracy_focus':
        verb = 'пересдай' if retry else 'пройди'
        subtitle = f'+{bonus_xp} XP · {verb} урок с проверкой на {int(CHALLENGE_ACCURACY_MIN_SCORE)}%+'
    elif not is_completed and category == 'speed_run':
        subtitle = f'+{bonus_xp} XP · урок с проверкой за {CHALLENGE_SPEED_RUN_MAX_SECONDS // 60} мин'

    base_url = f'/learn/{lesson_id}/' if lesson_id else '/learn/'
    if retry:
        base_url += '?retry=true'
    url = build_slot_url(base_url, LinearSlotKind.CHALLENGE)

    return PlanItem(
        id=f'challenge:{challenge_id}',
        section='optional',
        kind='challenge',
        title=title_map.get(category, 'Челлендж дня'),
        subtitle=subtitle,
        lesson_type=None,
        eta_minutes=0 if is_completed else _CHALLENGE_ETA_MINUTES,
        url=None if is_completed else url,
        completed=is_completed,
        completion_signal='challenge_completed',
        data={
            'is_challenge': True,
            'challenge_id': challenge_id,
            'category': category,
            'bonus_xp': bonus_xp,
            'challenge_streak': info.get('challenge_streak') or 0,
            'lesson_id': lesson_id,
            'retry': retry,
            'graded_only': category != 'listening_deep',
            'completed_score': (info.get('completion') or {}).get('score') if is_completed else None,
        },
    )


def _resolve_target_lesson(user_id: int, db: Any, category: str) -> tuple[Optional[int], bool]:
    """Return ``(lesson_id, retry)`` for a pending challenge, or ``(None, False)``.

    Only lessons whose completion can satisfy ``check_challenge_criteria``
    qualify (DP-048). Walking the spine past the next lesson is deliberately
    avoided: later lessons sit behind ``check_lesson_access`` and would 403.
    """
    from app.daily_plan.linear.progression import find_next_lesson_linear

    if category == 'listening_deep':
        from app.daily_plan.items.skills import (
            _LISTENING_LESSON_TYPES,
            _find_next_skill_lesson,
        )
        skill_lesson = _find_next_skill_lesson(user_id, db, _LISTENING_LESSON_TYPES)
        return (int(skill_lesson.id) if skill_lesson is not None else None), False

    next_lesson = find_next_lesson_linear(user_id, db)
    if next_lesson is not None and getattr(next_lesson, 'type', None) in CHALLENGE_GRADED_LESSON_TYPES:
        return int(next_lesson.id), False
    if category == 'accuracy_focus':
        last = _last_passed_graded_lesson(user_id, db)
        if last is not None:
            return int(last.id), True
    return None, False


def _last_passed_graded_lesson(user_id: int, db: Any):
    """Most recently completed server-graded lesson — the accuracy retake target."""
    from app.curriculum.models import LessonProgress, Lessons

    return (
        db.session.query(Lessons)
        .join(LessonProgress, LessonProgress.lesson_id == Lessons.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            Lessons.type.in_(list(CHALLENGE_GRADED_LESSON_TYPES)),
        )
        .order_by(LessonProgress.completed_at.desc().nullslast(), LessonProgress.id.desc())
        .first()
    )
