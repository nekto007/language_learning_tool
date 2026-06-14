"""Adaptive tier selection for the static daily plan.

Three tiers determine the required-section size:

- ``calm``      — 3 items (curriculum, SRS, book). Forced when a heavy
                  lesson (final_test) is next on the spine, or when the
                  user has been working sparingly over the last week.
- ``normal``    — 4 items (calm + a second curriculum lesson). Default.
- ``intensive`` — 5 items (normal + a third curriculum lesson). Reserved
                  for users who close the day consistently AND keep
                  reaching for optional work.

Tier is resolved at snapshot generation time (00:00 user-local or on
first lazy build) and frozen into the snapshot for the day — behaviour
changes within the same day do not promote/demote the active plan.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from datetime import timedelta
from typing import Any, Literal

logger = logging.getLogger(__name__)

Tier = Literal['calm', 'normal', 'intensive']

# Rolling window over which we count secured days and days with optional
# activity. 7 days reacts to behaviour changes within a week without
# punishing a one-off bad day.
WINDOW_DAYS = 7

# Under this many secured days in the window → calm tier.
SECURED_LOW = 3

# At or above this many secured days AND OPTIONAL_HIGH optional-activity
# days → intensive tier.
SECURED_HIGH = 5

# Days where the user did work beyond the required minimum.
OPTIONAL_HIGH = 3

# StreakEvent sources counted as "optional-section activity". These are
# the kinds that live in optional (or, for grammar_review, that the user
# does on their own initiative). Required-side sources (curriculum,
# srs:global, book reading) are excluded — they don't signal extra effort.
_OPTIONAL_SOURCES: frozenset[str] = frozenset({
    'linear_grammar_review',
    'linear_book_srs',
    'linear_error_review',
    'linear_listening',
    'linear_speaking',
    'linear_writing',
})


def compute_user_tier(user_id: int, db: Any) -> Tier:
    """Return the tier the user should receive for today.

    Forces ``calm`` when a ``final_test`` is the next spine lesson — the
    final test plus a grammar-prep step is already heavy enough; we do
    not want to pile a second/third curriculum slot on top.
    """
    from app.daily_plan.linear.progression import find_next_lesson_linear
    from app.utils.time_utils import get_user_local_date

    next_lesson = find_next_lesson_linear(user_id, db)
    if next_lesson is not None and getattr(next_lesson, 'type', None) == 'final_test':
        logger.debug("tier user=%s -> calm (final_test ahead)", user_id)
        return 'calm'

    today = get_user_local_date(user_id, db)
    window_start = today - timedelta(days=WINDOW_DAYS)

    secured_days = _count_secured_days(user_id, window_start, today, db)
    if secured_days < SECURED_LOW:
        logger.debug(
            "tier user=%s -> calm secured=%d/%d window=%dd",
            user_id, secured_days, SECURED_LOW, WINDOW_DAYS,
        )
        return 'calm'

    if secured_days >= SECURED_HIGH:
        optional_days = _count_days_with_optional_completion(
            user_id, window_start, today, db,
        )
        if optional_days >= OPTIONAL_HIGH:
            logger.debug(
                "tier user=%s -> intensive secured=%d optional=%d window=%dd",
                user_id, secured_days, optional_days, WINDOW_DAYS,
            )
            return 'intensive'

    logger.debug(
        "tier user=%s -> normal secured=%d window=%dd",
        user_id, secured_days, WINDOW_DAYS,
    )
    return 'normal'


def _count_secured_days(
    user_id: int,
    window_start: date_cls,
    today: date_cls,
    db: Any,
) -> int:
    """Count DailyPlanLog rows in ``[window_start, today)`` with secured_at set.

    Today is excluded — the tier shapes today's plan, so today's secured
    state is not yet observable when this runs.
    """
    from app.daily_plan.models import DailyPlanLog

    return (
        db.session.query(DailyPlanLog.id)
        .filter(
            DailyPlanLog.user_id == user_id,
            DailyPlanLog.plan_date >= window_start,
            DailyPlanLog.plan_date < today,
            DailyPlanLog.secured_at.isnot(None),
        )
        .count()
    )


def _count_days_with_optional_completion(
    user_id: int,
    window_start: date_cls,
    today: date_cls,
    db: Any,
) -> int:
    """Count distinct user-local days in the window with optional-source XP.

    Reads ``StreakEvent.event_date`` (a Date column already in the user's
    local day per ``maybe_award_*`` writers) so we don't need to translate
    naive UTC timestamps back through the user's timezone.
    """
    from sqlalchemy import distinct, func

    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE

    rows = (
        db.session.query(func.count(distinct(StreakEvent.event_date)))
        .filter(
            StreakEvent.user_id == user_id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.event_date >= window_start,
            StreakEvent.event_date < today,
            StreakEvent.details['source'].astext.in_(list(_OPTIONAL_SOURCES)),
        )
        .scalar()
    )
    return int(rows or 0)
