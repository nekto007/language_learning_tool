"""Error review slot — conditional 4th baseline slot on the linear spine.

Appears only when ``should_show_error_review`` is True: the user has at
least 5 unresolved quiz errors AND has not resolved anything in the past
3 days (or has never resolved one). Returns ``None`` otherwise — the
assembler filters out ``None`` slots.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

from app.daily_plan.linear.context import LinearSlotKind, build_slot_url

logger = logging.getLogger(__name__)
from app.daily_plan.linear.errors import (
    REVIEW_TRIGGER_COOLDOWN,
    count_unresolved,
    get_last_resolved_at,
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

    last_resolved = get_last_resolved_at(user_id, db)
    last_resolved_iso: Optional[str] = None
    hours_since_resolved: Optional[int] = None
    cooldown_remaining_hours = 0
    if last_resolved is not None:
        if last_resolved.tzinfo is None:
            last_resolved_aware = last_resolved.replace(tzinfo=timezone.utc)
        else:
            last_resolved_aware = last_resolved
        elapsed = datetime.now(timezone.utc) - last_resolved_aware
        elapsed_seconds = max(0.0, elapsed.total_seconds())
        hours_since_resolved = int(elapsed_seconds // 3600)
        last_resolved_iso = last_resolved_aware.isoformat()
        remaining = REVIEW_TRIGGER_COOLDOWN.total_seconds() - elapsed_seconds
        if remaining > 0:
            cooldown_remaining_hours = int(math.ceil(remaining / 3600))

    logger.info(
        "error_review_slot user=%s trigger=true unresolved=%d pool=%d "
        "hours_since_resolved=%s cooldown_remaining_hours=%d",
        user_id, unresolved, pool_size, hours_since_resolved, cooldown_remaining_hours,
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
            'last_resolved_at': last_resolved_iso,
            'hours_since_resolved': hours_since_resolved,
            'cooldown_remaining_hours': cooldown_remaining_hours,
        },
    )
