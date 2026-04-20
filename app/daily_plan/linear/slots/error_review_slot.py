"""Error review slot — conditional 4th baseline slot on the linear spine.

Appears only when ``should_show_error_review`` is True: the user has at
least 5 unresolved quiz errors AND has not resolved anything in the past
3 days (or has never resolved one). Returns ``None`` otherwise — the
assembler filters out ``None`` slots.
"""
from __future__ import annotations

from typing import Any, Optional

from app.daily_plan.linear.errors import (
    DEFAULT_REVIEW_POOL_LIMIT,
    count_unresolved,
    should_show_error_review,
)
from app.daily_plan.linear.slots import LinearSlot

_ERROR_REVIEW_SLOT_ETA_MINUTES = 6


def build_error_review_slot(user_id: int, db: Any) -> Optional[LinearSlot]:
    """Return the error-review slot when the trigger fires, else None."""
    if not should_show_error_review(user_id, db):
        return None

    unresolved = count_unresolved(user_id, db)
    pool_size = min(unresolved, DEFAULT_REVIEW_POOL_LIMIT)

    return LinearSlot(
        kind='error_review',
        title=f'Разбор ошибок ({unresolved})',
        lesson_type=None,
        eta_minutes=_ERROR_REVIEW_SLOT_ETA_MINUTES,
        url='/learn/error-review/?from=linear_plan',
        completed=False,
        data={
            'unresolved_count': unresolved,
            'pool_size': pool_size,
        },
    )
