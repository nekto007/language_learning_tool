"""Title/rank system for daily plan completions.

Users earn cumulative ranks based on the total number of completed daily plans.
Ranks are advisory titles; they have no gating effect on features.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


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
