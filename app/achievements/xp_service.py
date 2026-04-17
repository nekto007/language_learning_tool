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
