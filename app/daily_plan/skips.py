"""Slot-skip helpers shared by the unified plan + API layer.

Originally lived in ``app/daily_plan/linear/plan.py``. After collapsing
linear into unified, they were promoted to a flat top-level module so the
API/orchestrator no longer reach into the legacy ``linear/`` namespace
for skip primitives. ``linear/plan.py`` re-exports them for backward
compatibility with any external callers.
"""
from __future__ import annotations

from typing import Any, Optional

# One "not now" action per user-local day across all baseline slots.
DAILY_SLOT_SKIP_QUOTA = 1

# One curriculum-lesson deferral per user-local day.
DAILY_LESSON_SKIP_QUOTA = 1


def get_slot_skip_key(slot: dict[str, Any], index: Optional[int] = None) -> str:
    """Return a stable key identifying a single slot for skip dedup.

    Curriculum-backed slots carry a ``lesson_id`` so a skip stays bound to
    that lesson even after the user later completes it (the next render
    surfaces a different lesson and we don't want the skip to drift).
    Kind-only slots fall back to position + kind.
    """
    kind = slot.get('kind') or ''
    data = slot.get('data') or {}
    lesson_id = data.get('lesson_id')
    if lesson_id:
        return f'lesson:{lesson_id}'
    if index is not None:
        return f'slot:{index}:{kind}'
    return f'kind:{kind}'


def get_slot_skips_used_today(
    user_id: int,
    plan_date: Any,
    db_session: Any,
) -> int:
    """Return how many baseline-slot skips the user used today.

    Reads ``DailyPlanEvent(event_type='slot_skipped', plan_date=today)``
    and counts the rows. The quota check in
    ``/api/daily-plan/events`` enforces ``DAILY_SLOT_SKIP_QUOTA``.
    """
    from app.daily_plan.models import DailyPlanEvent

    return db_session.session.query(DailyPlanEvent).filter_by(
        user_id=user_id,
        event_type='slot_skipped',
        plan_date=plan_date,
    ).count()
