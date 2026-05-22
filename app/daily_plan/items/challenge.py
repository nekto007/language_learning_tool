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

logger = logging.getLogger(__name__)

_CHALLENGE_ETA_MINUTES = 7

# Map challenge categories to a CTA URL. ``listening_deep`` accepts any
# listening attempt today; speed_run / accuracy_focus apply to the next
# curriculum lesson, so we send the user to the standard /learn entry.
_CATEGORY_DEFAULT_URL = '/learn/'


def build_challenge_item(user_id: int, db: Any) -> Optional[PlanItem]:
    """Return today's daily-challenge PlanItem, or None on errors / already done.

    Already-completed challenges are intentionally skipped — they don't add
    value as a card after the bonus is claimed. Future enhancement could
    return a celebratory completed-state item; keep simple for now.
    """
    from app.daily_plan.challenge import get_today_challenge

    try:
        info = get_today_challenge(user_id, db)
    except Exception:  # pragma: no cover — challenge seeding is defensive
        logger.exception("challenge_item user=%s failed to load challenge", user_id)
        return None

    if info.get('is_completed'):
        return None

    category = info.get('category') or 'speed_run'
    bonus_xp = int(info.get('bonus_xp') or 0)
    challenge_id = info.get('id')

    title_map = {
        'speed_run': 'Челлендж дня: пройди урок быстро',
        'accuracy_focus': 'Челлендж дня: целься в точность',
        'listening_deep': 'Челлендж дня: глубокое аудирование',
    }
    subtitle = f'+{bonus_xp} XP · сегодня' if bonus_xp else 'Бонус-задание дня'

    return PlanItem(
        id=f'challenge:{challenge_id}',
        section='optional',
        kind='challenge',
        title=title_map.get(category, 'Челлендж дня'),
        subtitle=subtitle,
        lesson_type=None,
        eta_minutes=_CHALLENGE_ETA_MINUTES,
        url=_CATEGORY_DEFAULT_URL,
        completed=False,
        completion_signal='challenge_completed',
        data={
            'is_challenge': True,
            'challenge_id': challenge_id,
            'category': category,
            'bonus_xp': bonus_xp,
            'challenge_streak': info.get('challenge_streak') or 0,
        },
    )
