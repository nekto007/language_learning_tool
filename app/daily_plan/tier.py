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


# Lesson audit item 14 (2026-09-06): the pace is the learner's explicit choice.
# ``User.plan_difficulty`` ('light' / 'normal' / 'intensive') maps to 1 / 2 / 3
# curriculum lessons per day. The automatic ladder that used to pick the tier
# from secured days kept 98 % of snapshots on ``calm`` — a day rarely closed
# because the reading slot was unmet, so nobody ever left one lesson a day.
PACE_BY_DIFFICULTY: dict[str, int] = {'light': 1, 'normal': 2, 'intensive': 3}
DIFFICULTY_BY_PACE: dict[int, str] = {1: 'light', 2: 'normal', 3: 'intensive'}
TIER_BY_PACE: dict[int, Tier] = {1: 'calm', 2: 'normal', 3: 'intensive'}
DEFAULT_PACE = 2
# Recommend one more lesson a day when the learner hit the current pace on
# at least this many of the last WINDOW_DAYS study days.
PACE_UP_DAYS = 5


def pace_from_difficulty(value: Any) -> int:
    return PACE_BY_DIFFICULTY.get(str(value or '').lower(), DEFAULT_PACE)


def difficulty_for_pace(pace: int) -> str:
    return DIFFICULTY_BY_PACE.get(int(pace), DIFFICULTY_BY_PACE[DEFAULT_PACE])


def pace_for_user(user_id: int, db: Any) -> int:
    """Curriculum lessons per day the learner asked for (1..3)."""
    from app.auth.models import User

    value = db.session.query(User.plan_difficulty).filter(User.id == user_id).scalar()
    return pace_from_difficulty(value)


def compute_user_tier(user_id: int, db: Any) -> Tier:
    """Return the tier the user should receive for today.

    The tier is the learner's explicit pace (item 14). ``calm`` is still
    forced when a ``final_test`` is the next spine lesson — the final test
    plus a grammar-prep step is already heavy enough; we do not want to
    pile a second/third curriculum slot on top.
    """
    from app.daily_plan.linear.progression import find_next_lesson_linear

    next_lesson = find_next_lesson_linear(user_id, db)
    if next_lesson is not None and getattr(next_lesson, 'type', None) == 'final_test':
        logger.debug("tier user=%s -> calm (final_test ahead)", user_id)
        return 'calm'
    pace = pace_for_user(user_id, db)
    tier = TIER_BY_PACE.get(pace, 'normal')
    logger.debug("tier user=%s -> %s (pace=%d)", user_id, tier, pace)
    return tier


# Below this many pace-hit days in the window a learner with prior history is
# «behind» (item 15). Newcomers without any lesson before the window are never
# told they are behind.
PACE_BEHIND_DAYS = 3


def _days_hit_in_window(user_id: int, db: Any, pace: int) -> tuple[int, bool]:
    """(study days in the last WINDOW_DAYS with >= pace lessons done, has_history_before_window)."""
    from collections import Counter
    from datetime import UTC, datetime

    from app.curriculum.models import LessonProgress
    from app.utils.time_utils import (
        get_user_local_date,
        get_user_timezone_name,
        study_day_date_for_tz,
    )

    tz_name = get_user_timezone_name(user_id, db)
    today = get_user_local_date(user_id, db)
    window_start = today - timedelta(days=WINDOW_DAYS)
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=WINDOW_DAYS + 2)
    rows = (
        db.session.query(LessonProgress.completed_at)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            LessonProgress.completed_at.isnot(None),
            LessonProgress.completed_at >= since,
        )
        .all()
    )
    per_day: Counter = Counter()
    for (ts,) in rows:
        aware = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts
        day = study_day_date_for_tz(tz_name, now_utc=aware)
        if window_start <= day < today:
            per_day[day] += 1
    days_hit = sum(1 for n in per_day.values() if n >= pace)
    has_history = bool(
        db.session.query(LessonProgress.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            LessonProgress.completed_at.isnot(None),
            LessonProgress.completed_at < since,
        )
        .first()
    )
    return days_hit, has_history


def recommend_pace(user_id: int, db: Any) -> dict[str, int] | None:
    """Suggest one more lesson a day when the learner keeps hitting the pace.

    Counts study days in the last ``WINDOW_DAYS`` (today excluded) on which
    the learner completed at least ``pace`` curriculum lessons — course
    completion, not secured days (Codex, 2026-09-06): the day-secured signal
    depends on SRS and reading and says nothing about course appetite.
    Returns ``{'current', 'recommended', 'days_hit'}`` or None. Never
    suggests slowing down.
    """
    pace = pace_for_user(user_id, db)
    if pace >= max(TIER_BY_PACE):
        return None
    days_hit, _ = _days_hit_in_window(user_id, db, pace)
    if days_hit < PACE_UP_DAYS:
        return None
    return {'current': pace, 'recommended': pace + 1, 'days_hit': days_hit}


def pace_status(user_id: int, db: Any) -> dict[str, Any]:
    """Everything the plan header needs about the pace, in one pass (item 15).

    ``recommended`` (upward nudge, see :func:`recommend_pace`) and ``behind``
    are mutually exclusive by construction: behind needs fewer than
    ``PACE_BEHIND_DAYS`` hit days, the nudge at least ``PACE_UP_DAYS``.
    A learner with no completed lesson before the window is never behind —
    a newcomer's first week is not a slump.
    """
    pace = pace_for_user(user_id, db)
    days_hit, has_history = _days_hit_in_window(user_id, db, pace)
    recommended = pace + 1 if (pace < max(TIER_BY_PACE) and days_hit >= PACE_UP_DAYS) else None
    behind = bool(has_history and days_hit < PACE_BEHIND_DAYS)
    return {
        'lessons_per_day': pace,
        'days_hit': days_hit,
        'recommended': recommended,
        'behind': behind,
    }


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
