"""Error review slot — conditional 4th baseline slot on the linear spine.

Appears only when ``should_show_error_review`` is True: the user has at
least 5 unresolved quiz errors AND has not resolved anything in the past
3 days (or has never resolved one). Returns ``None`` otherwise — the
assembler filters out ``None`` slots.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.linear.context import LinearSlotKind, build_slot_url

logger = logging.getLogger(__name__)
from app.daily_plan.linear.errors import (
    count_unresolved,
    get_review_pool_size,
    should_show_error_review,
)
from app.daily_plan.linear.slots import LinearSlot

_ERROR_REVIEW_SLOT_ETA_MINUTES = 6


def build_error_review_slot(user_id: int, db: Any) -> Optional[LinearSlot]:
    """Return the error-review slot when the trigger fires, else None."""
    if not should_show_error_review(user_id, db):
        logger.debug("error_review_slot user=%s trigger=false skipped", user_id)
        return None

    unresolved = count_unresolved(user_id, db)
    pool_size = min(unresolved, get_review_pool_size(unresolved))

    logger.info(
        "error_review_slot user=%s trigger=true unresolved=%d pool=%d",
        user_id, unresolved, pool_size,
    )
    return LinearSlot(
        kind='error_review',
        title=f'Разбор ошибок ({unresolved})',
        lesson_type=None,
        eta_minutes=_ERROR_REVIEW_SLOT_ETA_MINUTES,
        url=build_slot_url('/learn/error-review/', LinearSlotKind.ERROR_REVIEW),
        completed=False,
        data={
            'unresolved_count': unresolved,
            'pool_size': pool_size,
        },
    )
