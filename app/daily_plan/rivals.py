"""Ghost rival for the Phase 3 route-board competition strip.

The ghost is never persisted. Its route_position is derived on every read
from a deterministic seed (user_id + date) and the fraction of the current
day that has elapsed in local time.

Adults only: users with birth_year set are checked for age >= 18. Users
with no birth_year (legacy accounts) are treated as adults.  Child users
(age < 18) must never see a rival strip or any competition framing.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, time as time_cls, timezone
from typing import Optional

_ADULT_AGE_THRESHOLD = 18

# The label shown in the UI — always this string, never claim it's a real user.
GHOST_RIVAL_LABEL = "Training Rival"

# Ghost names with deterministic avatar seeds.
_GHOST_AVATARS: tuple[tuple[str, int], ...] = (
    ("Луна", 1),
    ("Комета", 2),
    ("Орион", 3),
    ("Феникс", 4),
    ("Атлас", 5),
    ("Вега", 6),
    ("Сириус", 7),
    ("Полярная", 8),
)

# Active window during which the ghost's position grows linearly.
_RIVAL_START_HOUR = 8
_RIVAL_END_HOUR = 22

# Ghost targets between these fractions of the full route (100 steps).
# Kept below 1.0 so the ghost stays slightly behind an average user.
_RIVAL_TARGET_MIN_FRACTION = 0.55
_RIVAL_TARGET_MAX_FRACTION = 0.85


@dataclass
class GhostRival:
    """Synthesised rival for the route board. Not persisted.

    All fields are derived from the user's seed and the current time.
    display_label is always GHOST_RIVAL_LABEL; name is the internal nickname
    used for personalisation within the ghost pool.
    """

    name: str
    avatar_seed: int
    route_position: int  # 0–100
    display_label: str = field(default=GHOST_RIVAL_LABEL)


def is_adult_user(birth_year: Optional[int], reference_year: Optional[int] = None) -> bool:
    """Return True if the user is at least 18 years old.

    birth_year=None means unknown age — treated as adult for backward
    compatibility with existing accounts that predate this field.
    """
    if birth_year is None:
        return True
    current_year = reference_year or datetime.now(timezone.utc).year
    return current_year - birth_year >= _ADULT_AGE_THRESHOLD


def _rival_seed(user_id: int, race_date: date_cls) -> int:
    """Deterministic integer seed from user_id and date."""
    key = f"{user_id}:{race_date.isoformat()}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16)


def _progress_fraction(local_time: time_cls) -> float:
    """Fraction of the rival-active window [START_HOUR, END_HOUR] elapsed."""
    if _RIVAL_END_HOUR <= _RIVAL_START_HOUR:
        return 1.0
    current = local_time.hour + local_time.minute / 60.0
    if current <= _RIVAL_START_HOUR:
        return 0.0
    if current >= _RIVAL_END_HOUR:
        return 1.0
    return (current - _RIVAL_START_HOUR) / (_RIVAL_END_HOUR - _RIVAL_START_HOUR)


def _ghost_target_position(seed: int) -> int:
    """Deterministic target route position (0–100) in the slightly-behind band.

    Maps the seed into [_RIVAL_TARGET_MIN_FRACTION, _RIVAL_TARGET_MAX_FRACTION]
    of 100, so the ghost always finishes behind the average adult learner.
    """
    span = _RIVAL_TARGET_MAX_FRACTION - _RIVAL_TARGET_MIN_FRACTION
    fraction = _RIVAL_TARGET_MIN_FRACTION + (seed % 10_000) / 10_000.0 * span
    return int(round(fraction * 100))


def get_ghost_rival(
    user_id: int,
    race_date: date_cls,
    now: Optional[datetime] = None,
    *,
    tz: Optional[str] = None,
) -> GhostRival:
    """Return the deterministic ghost rival for user_id on race_date.

    Route position scales from 0 to the ghost's target over the active window
    (08:00–22:00 local time).  Past dates return the full target; future dates
    return 0.

    Caller is responsible for ensuring the user is an adult before calling this
    function (use is_adult_user).
    """
    import pytz
    from config.settings import DEFAULT_TIMEZONE

    tz_name = tz or DEFAULT_TIMEZONE
    try:
        tz_obj = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        tz_obj = pytz.timezone(DEFAULT_TIMEZONE)

    if now is None:
        now = datetime.now(tz_obj)
    elif now.tzinfo is None:
        now = tz_obj.localize(now)
    else:
        now = now.astimezone(tz_obj)

    seed = _rival_seed(user_id, race_date)
    avatar_index = seed % len(_GHOST_AVATARS)
    name, avatar_seed = _GHOST_AVATARS[avatar_index]
    target = _ghost_target_position(seed)

    local_today = now.date()
    if local_today < race_date:
        position = 0
    elif local_today > race_date:
        position = target
    else:
        position = int(round(target * _progress_fraction(now.time())))

    return GhostRival(
        name=name,
        avatar_seed=avatar_seed,
        route_position=position,
    )
