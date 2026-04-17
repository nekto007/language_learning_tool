"""XP (experience points) system for daily mission plan progression.

XP is awarded for completing mission phases, finishing all phases in a day,
and maintaining streaks. XP accumulates into an independent level separate
from the rank system.

Level formula: to reach level N from level N-1 requires (N-1)*100 XP.
Total XP needed to reach level N: 100 * (N-1)*N / 2
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XP award amounts per phase kind (used in Task 25 for integration)
# ---------------------------------------------------------------------------
PHASE_XP: dict[str, int] = {
    'recall': 15,
    'learn': 40,
    'use': 35,
    'read': 30,
    'check': 25,
    'close': 10,
    'bonus': 20,
}

PERFECT_DAY_BONUS_XP = 50
FIRST_OF_DAY_BONUS_XP = 10

# Streak multiplier: 1.0 + streak_days * 0.02, capped at 2.0
STREAK_MULTIPLIER_BASE = 1.0
STREAK_MULTIPLIER_STEP = 0.02
STREAK_MULTIPLIER_MAX = 2.0

# Perfect day multipliers: (min_consecutive_days, multiplier)
# Applied on top of the streak multiplier to the perfect day bonus XP.
PERFECT_DAY_MULTIPLIERS: list[tuple[int, float]] = [
    (7, 2.5),
    (5, 2.0),
    (3, 1.5),
    (2, 1.2),
    (1, 1.0),
]


# ---------------------------------------------------------------------------
# Level thresholds
# ---------------------------------------------------------------------------

def xp_for_level(level: int) -> int:
    """Total XP required to reach `level` (from level 1).

    Level 1 starts at 0 XP.
    Reaching level N requires an additional (N-1)*100 XP on top of level N-1.
    Total XP = 100 * (level-1) * level / 2
    """
    if level <= 1:
        return 0
    n = level - 1
    return 100 * n * (n + 1) // 2


def get_perfect_day_multiplier(consecutive_days: int) -> float:
    """Return the perfect day XP multiplier for a consecutive perfect day count."""
    if consecutive_days is None or consecutive_days < 1:
        return 1.0
    for threshold, mult in PERFECT_DAY_MULTIPLIERS:
        if consecutive_days >= threshold:
            return mult
    return 1.0


def get_perfect_day_info(user_id: int) -> dict:
    """Return current perfect day streak info for dashboard display.

    Returns a dict with consecutive_days, current_multiplier, next_multiplier,
    and a human-readable message about tomorrow's bonus.
    """
    from app.achievements.models import UserStatistics

    stats = UserStatistics.query.filter_by(user_id=user_id).first()
    consecutive = int(getattr(stats, 'consecutive_perfect_days', 0) or 0) if stats else 0
    current_mult = get_perfect_day_multiplier(consecutive)
    next_mult = get_perfect_day_multiplier(consecutive + 1)

    if consecutive > 0 and next_mult > current_mult:
        message = f'Perfect day streak: {consecutive} days! Tomorrow: {next_mult:.1f}x bonus'
    elif consecutive > 0:
        message = f'Perfect day streak: {consecutive} days! {current_mult:.1f}x bonus active'
    else:
        message = ''

    return {
        'consecutive_days': consecutive,
        'current_multiplier': current_mult,
        'next_multiplier': next_mult,
        'message': message,
    }


def get_streak_multiplier(streak_days: int) -> float:
    """Return the streak XP multiplier clamped to [1.0, 2.0]."""
    if streak_days is None or streak_days < 0:
        streak_days = 0
    raw = STREAK_MULTIPLIER_BASE + streak_days * STREAK_MULTIPLIER_STEP
    return min(raw, STREAK_MULTIPLIER_MAX)


@dataclass(frozen=True)
class LevelInfo:
    """Snapshot of a user's XP/level state."""

    current_level: int
    total_xp: int
    xp_in_level: int
    xp_to_next: int
    progress_percent: float


def get_level_info(total_xp: int) -> LevelInfo:
    """Return level details for a given cumulative XP total."""
    if total_xp is None or total_xp < 0:
        total_xp = 0

    level = 1
    while True:
        next_threshold = xp_for_level(level + 1)
        if total_xp < next_threshold:
            break
        level += 1

    level_start = xp_for_level(level)
    level_end = xp_for_level(level + 1)
    span = level_end - level_start
    within = total_xp - level_start

    if span > 0:
        progress = min(100.0, round((within / span) * 100, 1))
    else:
        progress = 100.0

    return LevelInfo(
        current_level=level,
        total_xp=total_xp,
        xp_in_level=within,
        xp_to_next=max(0, level_end - total_xp),
        progress_percent=progress,
    )


@dataclass(frozen=True)
class XPAward:
    """Result of an XP award operation."""

    xp_awarded: int
    multiplier: float
    new_total_xp: int
    previous_level: int
    new_level: int
    leveled_up: bool


def award_phase_xp_idempotent(
    user_id: int,
    phase_id: str,
    phase_mode: str,
    for_date: date,
) -> XPAward | None:
    """Award XP for a completed phase, idempotent (once per phase per day).

    Returns XPAward if awarded, None if already awarded for this phase today.
    Caller must commit the session.
    """
    from app.achievements.models import StreakEvent
    from app.utils.db import db

    already = StreakEvent.query.filter_by(
        user_id=user_id,
        event_type='xp_phase',
        event_date=for_date,
    ).filter(
        StreakEvent.details['phase_id'].astext == phase_id
    ).first()
    if already:
        return None

    base = PHASE_XP.get(phase_mode, PHASE_XP.get('check', 25))
    result = award_xp(user_id, base, f'phase:{phase_mode}')

    db.session.add(StreakEvent(
        user_id=user_id,
        event_type='xp_phase',
        event_date=for_date,
        coins_delta=0,
        details={'phase_id': phase_id, 'mode': phase_mode, 'xp': result.xp_awarded},
    ))
    return result


def award_perfect_day_xp_idempotent(
    user_id: int,
    for_date: date,
) -> XPAward | None:
    """Award perfect day bonus XP, once per day.

    Tracks consecutive perfect days and applies an escalating multiplier:
    2 days=1.2x, 3 days=1.5x, 5 days=2.0x, 7+ days=2.5x (on top of streak
    multiplier). Missing a day resets the counter to 1.

    Returns XPAward if awarded, None if already awarded today.
    Caller must commit the session.
    """
    from app.achievements.models import UserStatistics, StreakEvent
    from app.utils.db import db

    already = StreakEvent.query.filter_by(
        user_id=user_id,
        event_type='xp_perfect_day',
        event_date=for_date,
    ).first()
    if already:
        return None

    # Determine consecutive perfect day count
    yesterday = for_date - timedelta(days=1)
    had_yesterday = StreakEvent.query.filter_by(
        user_id=user_id,
        event_type='xp_perfect_day',
        event_date=yesterday,
    ).first() is not None

    stats = UserStatistics.query.filter_by(user_id=user_id).first()
    if stats is None:
        stats = UserStatistics(user_id=user_id)
        db.session.add(stats)
        db.session.flush()

    current_consecutive = int(stats.consecutive_perfect_days or 0)
    new_consecutive = current_consecutive + 1 if had_yesterday else 1
    stats.consecutive_perfect_days = new_consecutive

    perfect_mult = get_perfect_day_multiplier(new_consecutive)
    adjusted_base = max(1, int(PERFECT_DAY_BONUS_XP * perfect_mult))

    result = award_xp(user_id, adjusted_base, 'perfect_day')

    db.session.add(StreakEvent(
        user_id=user_id,
        event_type='xp_perfect_day',
        event_date=for_date,
        coins_delta=0,
        details={
            'xp': result.xp_awarded,
            'consecutive_days': new_consecutive,
            'perfect_day_multiplier': perfect_mult,
        },
    ))
    return result


def award_xp(user_id: int, base_amount: int, source: str) -> XPAward:
    """Award XP to a user with streak multiplier applied.

    Idempotency is the caller's responsibility (e.g. only call once per phase
    completion). Updates UserStatistics.total_xp and current_level in-place;
    the caller must commit the session.
    """
    from app.achievements.models import UserStatistics
    from app.utils.db import db

    if base_amount <= 0:
        raise ValueError(f"base_amount must be positive, got {base_amount}")

    stats = UserStatistics.query.filter_by(user_id=user_id).first()
    if stats is None:
        stats = UserStatistics(user_id=user_id)
        db.session.add(stats)
        db.session.flush()

    streak_days = int(stats.current_streak_days or 0)
    multiplier = get_streak_multiplier(streak_days)
    awarded = max(1, round(base_amount * multiplier))

    previous_total = int(stats.total_xp or 0)
    previous_level = get_level_info(previous_total).current_level

    new_total = previous_total + awarded
    new_info = get_level_info(new_total)

    stats.total_xp = new_total
    stats.current_level = new_info.current_level

    leveled_up = new_info.current_level > previous_level
    if leveled_up:
        logger.info(
            "user %s leveled up to %s (source=%s, xp=%s)",
            user_id, new_info.current_level, source, new_total,
        )

    return XPAward(
        xp_awarded=awarded,
        multiplier=multiplier,
        new_total_xp=new_total,
        previous_level=previous_level,
        new_level=new_info.current_level,
        leveled_up=leveled_up,
    )
