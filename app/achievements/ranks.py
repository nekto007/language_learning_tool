"""Title/rank system for daily plan completions.

Users earn cumulative ranks based on the total number of completed daily plans.
Ranks are advisory titles; they have no gating effect on features.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


# (threshold, rank_code, display_name)
# Ordered ascending by threshold. The list is the single source of truth for
# rank progression and is consumed by both the model layer and the templates.
RANK_THRESHOLDS: list[tuple[int, str, str]] = [
    (0, 'novice', 'Novice'),
    (7, 'explorer', 'Explorer'),
    (21, 'student', 'Student'),
    (50, 'expert', 'Expert'),
    (100, 'master', 'Master'),
    (200, 'legend', 'Legend'),
    (365, 'grandmaster', 'Grandmaster'),
]


@dataclass(frozen=True)
class RankInfo:
    """Snapshot of a user's rank progression at a point in time."""

    code: str
    name: str
    threshold: int
    plans_completed: int
    next_code: Optional[str]
    next_name: Optional[str]
    next_threshold: Optional[int]
    progress_percent: float
    plans_to_next: Optional[int]


def _normalize(plans_completed: int) -> int:
    if plans_completed is None or plans_completed < 0:
        return 0
    return int(plans_completed)


def get_user_rank(plans_completed: int) -> RankInfo:
    """Return rank metadata for a given cumulative plan-completion count."""

    plans = _normalize(plans_completed)

    current_idx = 0
    for idx, (threshold, _code, _name) in enumerate(RANK_THRESHOLDS):
        if plans >= threshold:
            current_idx = idx
        else:
            break

    cur_threshold, cur_code, cur_name = RANK_THRESHOLDS[current_idx]

    if current_idx + 1 < len(RANK_THRESHOLDS):
        next_threshold, next_code, next_name = RANK_THRESHOLDS[current_idx + 1]
        span = next_threshold - cur_threshold
        within = plans - cur_threshold
        if span > 0:
            progress = max(0.0, min(100.0, round((within / span) * 100, 1)))
        else:
            progress = 100.0
        plans_to_next = max(0, next_threshold - plans)
        return RankInfo(
            code=cur_code,
            name=cur_name,
            threshold=cur_threshold,
            plans_completed=plans,
            next_code=next_code,
            next_name=next_name,
            next_threshold=next_threshold,
            progress_percent=progress,
            plans_to_next=plans_to_next,
        )

    return RankInfo(
        code=cur_code,
        name=cur_name,
        threshold=cur_threshold,
        plans_completed=plans,
        next_code=None,
        next_name=None,
        next_threshold=None,
        progress_percent=100.0,
        plans_to_next=None,
    )


def get_rank_code(plans_completed: int) -> str:
    """Return only the rank code for the given completion count."""

    return get_user_rank(plans_completed).code


def get_rank_name(plans_completed: int) -> str:
    """Return only the rank display name for the given completion count."""

    return get_user_rank(plans_completed).name


def is_rank_up(previous_count: int, new_count: int) -> bool:
    """Return True if `new_count` crosses into a higher rank than `previous_count`."""

    return get_rank_code(new_count) != get_rank_code(previous_count) and new_count > previous_count


@dataclass(frozen=True)
class RankUp:
    """Details of a rank promotion."""

    previous_code: str
    previous_name: str
    new_code: str
    new_name: str
    plans_completed: int


def _has_plan_completion_marker(user_id: int, for_date: date) -> bool:
    from app.achievements.models import StreakEvent

    return StreakEvent.query.filter_by(
        user_id=user_id,
        event_type='plan_completed',
        event_date=for_date,
    ).first() is not None


def record_plan_completion(
    user_id: int, for_date: Optional[date] = None,
) -> Optional[RankUp]:
    """Record a full daily plan completion and detect rank-up.

    Idempotent per day: writes a `plan_completed` StreakEvent marker once and
    increments `UserStatistics.plans_completed_total` only on the first call
    for a given date. Updates `UserStatistics.current_rank` and returns a
    `RankUp` describing the promotion if the threshold was crossed.
    """
    from app.achievements.models import StreakEvent, UserStatistics
    from app.utils.db import db

    today = for_date or date.today()

    if _has_plan_completion_marker(user_id, today):
        return None

    stats = UserStatistics.query.filter_by(user_id=user_id).first()
    if stats is None:
        stats = UserStatistics(user_id=user_id)
        db.session.add(stats)
        db.session.flush()

    previous_count = int(stats.plans_completed_total or 0)
    previous_info = get_user_rank(previous_count)
    new_count = previous_count + 1
    new_info = get_user_rank(new_count)

    stats.plans_completed_total = new_count
    stats.current_rank = new_info.code

    db.session.add(StreakEvent(
        user_id=user_id,
        event_type='plan_completed',
        coins_delta=0,
        event_date=today,
        details={
            'plans_completed_total': new_count,
            'rank_code': new_info.code,
        },
    ))

    if new_info.code != previous_info.code:
        return RankUp(
            previous_code=previous_info.code,
            previous_name=previous_info.name,
            new_code=new_info.code,
            new_name=new_info.name,
            plans_completed=new_count,
        )
    return None


def check_rank_up(user_id: int) -> Optional[RankUp]:
    """Compare stored rank on UserStatistics against the rank derived from
    the current `plans_completed_total`. Returns a `RankUp` when they drift
    (e.g., after an admin backfill) or None when in sync.
    """
    from app.achievements.models import UserStatistics

    stats = UserStatistics.query.filter_by(user_id=user_id).first()
    if stats is None:
        return None

    plans = int(stats.plans_completed_total or 0)
    stored_code = stats.current_rank or 'novice'
    current_info = get_user_rank(plans)

    if stored_code == current_info.code:
        return None

    previous_info = next(
        (
            RankInfo(
                code=code, name=name, threshold=threshold,
                plans_completed=plans,
                next_code=None, next_name=None, next_threshold=None,
                progress_percent=0.0, plans_to_next=None,
            )
            for threshold, code, name in RANK_THRESHOLDS
            if code == stored_code
        ),
        get_user_rank(0),
    )

    return RankUp(
        previous_code=previous_info.code,
        previous_name=previous_info.name,
        new_code=current_info.code,
        new_name=current_info.name,
        plans_completed=plans,
    )
