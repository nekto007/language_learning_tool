"""Daily challenge item builder for the unified daily plan.

Challenges live in ``optional`` only — they never gate ``day_secured``.
The challenge surfaces with its ``bonus_xp`` so the dashboard can render
the multiplier. ``data.is_challenge=True`` lets the UI style the card
distinctly (highlight, badge).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

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

    # Resolve the target lesson for the challenge:
    #   - listening_deep → DailyChallenge.lesson_id (pre-pinned dictation/listening
    #     when seeded with a chosen lesson); fall back to the next listening
    #     lesson on the user's spine.
    #   - speed_run / accuracy_focus → the user's next curriculum lesson.
    # If nothing resolves (spine exhausted, no challenge lesson), fall back
    # to ``/learn/`` — better than a 404, even though it loses plan ctx.
    lesson_id = info.get('lesson_id')
    if lesson_id is None:
        try:
            from app.daily_plan.linear.progression import find_next_lesson_linear
            next_lesson = find_next_lesson_linear(user_id, db)
            if category == 'listening_deep':
                from app.daily_plan.items.skills import (
                    _LISTENING_LESSON_TYPES,
                    _find_next_skill_lesson,
                )
                skill_lesson = _find_next_skill_lesson(user_id, db, _LISTENING_LESSON_TYPES)
                lesson_id = skill_lesson.id if skill_lesson is not None else (
                    next_lesson.id if next_lesson is not None else None
                )
            else:
                lesson_id = next_lesson.id if next_lesson is not None else None
        except Exception:
            logger.exception("challenge_item user=%s lesson resolution failed", user_id)
            lesson_id = None

    base_url = f'/learn/{lesson_id}/' if lesson_id else '/learn/'
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
            'completed_score': (info.get('completion') or {}).get('score') if is_completed else None,
        },
    )
