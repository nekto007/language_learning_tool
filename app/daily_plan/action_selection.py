"""Shared selection of the next existing unified-plan item.

Selection does not assemble a plan, change its frozen contents, or decide
whether a separate presentation surface should unlock optional activities.
Callers provide the authoritative plan and computed completion map.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def next_unified_item(
    plan: Mapping[str, Any],
    completion: Mapping[str, bool] | None,
) -> dict[str, Any] | None:
    """Return the first actionable required/optional item without mutation.

    The original item is returned, preserving identity, its resume URL, and
    all query parameters. Completed, skipped, blocked, and URL-less items
    are ignored. A pause wins over any stale items left in the payload.
    """
    metadata = plan.get('_plan_meta') or {}
    if plan.get('mode') == 'paused' or metadata.get('effective_mode') == 'paused':
        return None

    completion = completion or {}
    for item in (plan.get('required') or []) + (plan.get('optional') or []):
        if (
            not completion.get(item.get('id', ''), False)
            and not item.get('completed', False)
            and not item.get('skipped', False)
            and not item.get('blocked', False)
            and item.get('url')
        ):
            return item
    return None
