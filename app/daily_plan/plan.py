"""Unified daily plan orchestrator.

Builds a single plan payload with three sections:

- ``required``  — minimum learning work that closes the day. ``day_secured``
  depends solely on this list.
- ``optional``  — bonus work, up to ``OPTIONAL_MAX`` items, priority-ordered.
- ``setup``     — non-blocking preparation (pick a book, browse catalogue).

Milestone events (day/module/level/book completed) are off-band via the
Notification mechanism; they never appear in the plan payload.

The orchestrator is timezone-agnostic — item builders read authoritative
DB state. ``day_secured`` is recomputed at the API layer from real activity
(``compute_plan_steps`` + ``compute_day_secured_from_activity``).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.items import PlanItem
from app.daily_plan.items.challenge import build_challenge_item
from app.daily_plan.items.curriculum import build_curriculum_item, has_completed_history
from app.daily_plan.items.error_review import build_error_review_item, determine_section
from app.daily_plan.items.reading import build_reading_item, get_user_reading_preference
from app.daily_plan.items.setup import (
    book_selected_today,
    build_setup_book_item,
    build_setup_level_item,
)
from app.daily_plan.items.skills import (
    build_listening_item,
    build_speaking_item,
    build_writing_item,
)
from app.daily_plan.items.srs import build_srs_item

logger = logging.getLogger(__name__)

OPTIONAL_MAX = 10

# Priority order for building optional items. Items already present in
# required (matched by ``id``) are skipped to avoid duplication.
_OPTIONAL_PRIORITY = (
    'curriculum',
    'srs',
    'reading',
    'listening',
    'speaking',
    'writing',
    'error_review',
    'challenge',
)


def build_required(
    user_id: int,
    db: Any,
    *,
    difficulty: str,
    focus: Optional[str],
) -> list[PlanItem]:
    """Assemble the required-section items in caskade order.

    Order: error_review (acute) → SRS (if due > 0) → curriculum → reading
    (if book selected and not selected today) → listening (when in module
    and difficulty != 'light').

    Setup items NEVER appear here. Empty list is valid (orchestrator
    reports day not secured and surfaces setup hints).
    """
    items: list[PlanItem] = []

    err_section = determine_section(user_id, db)
    if err_section == 'required':
        item = build_error_review_item(user_id, db, section='required')
        if item is not None:
            items.append(item)

    srs_item = build_srs_item(user_id, db, section='required')
    if srs_item is not None:
        items.append(srs_item)

    cur_item = build_curriculum_item(user_id, db, section='required')
    if cur_item is not None:
        items.append(cur_item)

    # Reading joins required only when a book is selected AND the selection
    # is NOT from today — otherwise a mid-day book pick would retroactively
    # void an already-secured day. The freshly-picked book lives in optional
    # today and joins required tomorrow.
    pref = get_user_reading_preference(user_id, db)
    if pref is not None and not book_selected_today(user_id, db):
        reading_item = build_reading_item(user_id, db, section='required', focus=focus)
        if reading_item is not None:
            items.append(reading_item)

    if difficulty != 'light':
        listening_item = build_listening_item(user_id, db, section='required')
        if listening_item is not None:
            items.append(listening_item)

    # Difficulty caps for required.
    if difficulty == 'light':
        items = items[:2]
    elif difficulty == 'normal':
        items = items[:4]
    # intensive: no cap

    return items


def build_optional(
    user_id: int,
    db: Any,
    *,
    required_items: list[PlanItem],
    focus: Optional[str],
    max_items: int = OPTIONAL_MAX,
) -> tuple[list[PlanItem], bool]:
    """Return (optional_items, has_more) capped at ``max_items``.

    Items already in required (matched by ``id``) are excluded. ``has_more``
    is True if a builder still had pending work when the cap was reached.
    """
    seen_ids = {it.id for it in required_items}
    items: list[PlanItem] = []
    builders_exhausted: dict[str, bool] = {k: False for k in _OPTIONAL_PRIORITY}

    # Build candidate items per source. Each source contributes at most one
    # optional item (subsequent extension comes from rebuild after activity).
    candidates: list[Optional[PlanItem]] = []
    for kind in _OPTIONAL_PRIORITY:
        candidate = _build_optional_candidate(user_id, db, kind, focus)
        if candidate is None:
            builders_exhausted[kind] = True
        elif candidate.id in seen_ids:
            # Already required — count as not exhausted but skip.
            continue
        else:
            candidates.append(candidate)
            seen_ids.add(candidate.id)

    items = [c for c in candidates if c is not None][:max_items]
    has_more = len(candidates) > max_items or any(
        not exhausted for kind, exhausted in builders_exhausted.items()
        if kind != 'challenge'  # challenge always single, never "more"
    )
    # ``has_more`` is a soft hint; the dashboard simply re-fetches on demand.
    return items, has_more


def _build_optional_candidate(
    user_id: int, db: Any, kind: str, focus: Optional[str],
) -> Optional[PlanItem]:
    if kind == 'curriculum':
        return build_curriculum_item(user_id, db, section='optional')
    if kind == 'srs':
        return build_srs_item(user_id, db, section='optional')
    if kind == 'reading':
        return build_reading_item(user_id, db, section='optional', focus=focus)
    if kind == 'listening':
        return build_listening_item(user_id, db, section='optional')
    if kind == 'speaking':
        return build_speaking_item(user_id, db, section='optional')
    if kind == 'writing':
        return build_writing_item(user_id, db, section='optional')
    if kind == 'error_review':
        section = determine_section(user_id, db)
        if section != 'optional':
            return None
        return build_error_review_item(user_id, db, section='optional')
    if kind == 'challenge':
        return build_challenge_item(user_id, db)
    return None


def build_setup(user_id: int, db: Any) -> list[PlanItem]:
    """Build the setup section.

    Emits:
    - ``setup_book`` when no ``UserReadingPreference`` exists.
    - ``setup_level`` when ``find_next_lesson_linear`` is None AND the user
      has no completion history (no eligible content).

    Both are independent — a fresh user with no book and no eligible lesson
    sees both, in this stable order.
    """
    items: list[PlanItem] = []

    pref = get_user_reading_preference(user_id, db)
    if pref is None:
        items.append(build_setup_book_item())

    from app.daily_plan.linear.progression import find_next_lesson_linear

    next_lesson = find_next_lesson_linear(user_id, db)
    if next_lesson is None and not has_completed_history(user_id, db):
        items.append(build_setup_level_item())

    return items


def get_daily_plan(
    user_id: int,
    db_session: Any = None,
) -> dict[str, Any]:
    """Assemble the unified daily plan payload for the user."""
    from app.daily_plan.linear.plan import (
        _level_progress_to_dict,
        _position_from_lesson,
        _get_user_focus,
        get_plan_intensity,
    )
    from app.daily_plan.linear.progression import (
        find_next_lesson_linear,
        get_user_level_progress,
    )
    from app.daily_plan.linear.chain import _get_plan_difficulty
    from app.utils.db import db

    session = db_session if db_session is not None else db

    logger.info("unified_plan_assemble user=%s start", user_id)

    next_lesson = find_next_lesson_linear(user_id, session)
    level_progress = get_user_level_progress(user_id, session, next_lesson=next_lesson)
    focus = _get_user_focus(user_id, session)
    difficulty = _get_plan_difficulty(user_id, session)

    required = build_required(user_id, session, difficulty=difficulty, focus=focus)
    optional, has_more_optional = build_optional(
        user_id, session, required_items=required, focus=focus
    )
    setup = build_setup(user_id, session)

    # Assembly-time day_secured is always False — required items start
    # uncompleted. API layer recomputes from actual activity.
    day_secured = False

    total_estimated_minutes = sum(
        it.eta_minutes for it in required if not it.completed
    )

    logger.info(
        "unified_plan_assemble user=%s done req=%d opt=%d setup=%d intensity=%s focus=%s",
        user_id, len(required), len(optional), len(setup), difficulty, focus or 'none',
    )

    if not required:
        logger.warning(
            "unified_plan_assemble user=%s required=[] — all sources exhausted "
            "or blocked. setup=%s",
            user_id, [it.kind for it in setup],
        )

    return {
        'mode': 'unified',
        'position': _position_from_lesson(next_lesson),
        'progress': _level_progress_to_dict(level_progress),
        'required': [it.to_dict() for it in required],
        'optional': [it.to_dict() for it in optional],
        'setup': [it.to_dict() for it in setup],
        'day_secured': day_secured,
        'total_estimated_minutes': total_estimated_minutes,
        'plan_intensity': get_plan_intensity(total_estimated_minutes),
        'has_more_optional': has_more_optional,
    }
