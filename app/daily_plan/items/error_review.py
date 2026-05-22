"""Error-review item builder for the unified daily plan.

The legacy linear plan placed error review in baseline whenever
``should_show_error_review`` fired (unresolved ≥ 5 + cooldown). The unified
model uses a higher bar for ``required`` because mid-day error review
nags users with minor backlogs:

- ``required`` only when unresolved ≥ 15 OR the user just had 3 failed
  lesson attempts in a row. This is the "acute" tier.
- ``optional`` when unresolved ≥ 5 (legacy trigger). Surfaces in the
  bonus list so users with smaller backlogs can pick it up voluntarily.
- Skipped entirely when unresolved < 5 OR the cooldown has not elapsed.

The orchestrator inspects ``count_unresolved`` and ``had_recent_failures``
to decide which tier (or skip) — the builder itself simply builds an item
in the section it's told.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

from app.daily_plan.items import PlanItem
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.errors import (
    REVIEW_TRIGGER_COOLDOWN,
    REVIEW_TRIGGER_MIN_UNRESOLVED,
    count_unresolved,
    get_last_resolved_at,
    get_review_pool_size,
    should_show_error_review,
)

_ERROR_REVIEW_ETA_MINUTES = 6

# Unified plan thresholds.
REQUIRED_UNRESOLVED_THRESHOLD = 15
RECENT_FAILURE_WINDOW = 3  # last N lesson attempts inspected for required-tier


def had_recent_failures(user_id: int, db: Any) -> bool:
    """True when the user's last ``RECENT_FAILURE_WINDOW`` lesson attempts all failed."""
    from app.curriculum.models import LessonAttempt

    rows = (
        db.session.query(LessonAttempt.passed)
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.completed_at.isnot(None),
        )
        .order_by(LessonAttempt.completed_at.desc())
        .limit(RECENT_FAILURE_WINDOW)
        .all()
    )
    if len(rows) < RECENT_FAILURE_WINDOW:
        return False
    return all(not row.passed for row in rows)


def determine_section(user_id: int, db: Any) -> Optional[str]:
    """Decide where error-review belongs (or None to skip).

    Returns:
        ``'required'`` — unresolved ≥ 15 OR ``had_recent_failures`` AND
                          cooldown elapsed.
        ``'optional'`` — unresolved ≥ 5 AND cooldown elapsed.
        ``None``       — below trigger, skip entirely.
    """
    if not should_show_error_review(user_id, db):
        return None
    unresolved = count_unresolved(user_id, db)
    if unresolved >= REQUIRED_UNRESOLVED_THRESHOLD or had_recent_failures(user_id, db):
        return 'required'
    return 'optional'


def build_error_review_item(
    user_id: int,
    db: Any,
    *,
    section: str,
) -> Optional[PlanItem]:
    """Build an error-review item. Caller decides section."""
    if not should_show_error_review(user_id, db):
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

    return PlanItem(
        id='error_review:global',
        section=section,  # type: ignore[arg-type]
        kind='error_review',
        title=f'Разбор ошибок ({unresolved})',
        subtitle=f'{pool_size} вопросов · {unresolved} в очереди',
        lesson_type=None,
        eta_minutes=_ERROR_REVIEW_ETA_MINUTES,
        url=build_slot_url('/learn/error-review/', LinearSlotKind.ERROR_REVIEW),
        completed=False,
        completion_signal='error_review_done',
        data={
            'unresolved_count': unresolved,
            'pool_size': pool_size,
            'last_resolved_at': last_resolved_iso,
            'hours_since_resolved': hours_since_resolved,
            'cooldown_remaining_hours': cooldown_remaining_hours,
        },
    )


__all__ = [
    'REQUIRED_UNRESOLVED_THRESHOLD',
    'RECENT_FAILURE_WINDOW',
    'REVIEW_TRIGGER_MIN_UNRESOLVED',
    'had_recent_failures',
    'determine_section',
    'build_error_review_item',
]
