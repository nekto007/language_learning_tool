"""SRS review item builder for the unified daily plan.

Returns a ``PlanItem`` for the user's due SRS cards when there is at least
one card due. Returns None when there are no due cards — the orchestrator
then skips SRS in required entirely (no fake «nothing due» placeholder).

Completion is determined out-of-band at API serialization time
(``compute_plan_steps`` checks XP earned today / cards reviewed today).
The builder always emits ``completed=False`` at assembly time.

The deck-quiz / card-lesson reinforcement mode from the legacy slot is
dropped: in the unified plan, freshly learned vocabulary lands in
``UserCardDirection`` and surfaces via normal SRS on subsequent days,
which is the cleaner reinforcement loop. Deck-quizzes for custom decks
remain available via the existing /study/quiz/* routes but are not part
of the daily plan as a dedicated slot.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.items import PlanItem
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url

logger = logging.getLogger(__name__)

_SRS_ITEM_ETA_MINUTES = 8


def _srs_completed_today(user_id: int, db: Any) -> bool:
    """Return True when the user earned SRS-slot XP today."""
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date

    today = get_linear_event_local_date(user_id, db)
    query = db.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.event_date == today,
        StreakEvent.details['source'].astext == 'linear_srs_global',
    )
    return db.session.query(query.exists()).scalar() or False


def build_srs_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'required',
) -> Optional[PlanItem]:
    """Return SRS PlanItem: pending when due>0, done when reviewed today, None otherwise.

    When due_count drops to zero mid-session, returning None would make the
    slot disappear from required and shrink the counter — confusing UX.
    Instead, if the user already earned the SRS-slot XP today, keep the
    item with completed=True so it stays on the «done» list. Only return
    None when due=0 AND no activity today (e.g. brand-new user with no
    cards yet).
    """
    from app.srs.counting import count_due_cards, count_new_cards_today, get_new_card_budget
    from app.study.services import SRSService
    from app.study.models import StudySettings
    from app.daily_plan.linear.slots.srs_slot import (
        count_linear_plan_srs_due_cards,
        count_srs_reviews_today,
    )

    due_count = count_linear_plan_srs_due_cards(user_id, db)
    reviews_today = count_srs_reviews_today(user_id, db)
    completed_today = _srs_completed_today(user_id, db)

    if due_count <= 0 and not completed_today:
        return None

    # In optional, don't surface a "done today" placeholder — keep the
    # bonus list focused on actionable items. Required keeps the done
    # card so the user can see progress and the counter reflects it.
    if section == 'optional' and due_count <= 0 and completed_today:
        return None

    backlog = count_due_cards(user_id, db)
    remaining_new, _ = get_new_card_budget(user_id, db)
    settings = StudySettings.get_settings(user_id)
    reviews_limit = max(int(settings.reviews_per_day or 0), 0)
    new_today = count_new_cards_today(user_id, db)
    limit_reason = SRSService.get_adaptive_limit_reason(user_id)

    data: dict[str, Any] = {
        'due_count': due_count,
        'backlog_due_count': backlog,
        'reviews_today': reviews_today,
        'reviews_limit': reviews_limit,
        'reviews_remaining': max(reviews_limit - reviews_today, 0),
        'new_count': new_today,
        'new_budget': remaining_new,
        'budget_remaining': remaining_new,
        'srs_limit_reason': limit_reason,
    }

    if due_count <= 0 and completed_today:
        title = 'Повторение засчитано'
        subtitle = f'{reviews_today} карточек · на сегодня всё' if reviews_today else 'на сегодня всё'
    else:
        title = f'Повторить {due_count} карточек'
        subtitle = f'{due_count} к повторению'

    return PlanItem(
        id='srs:global',
        section=section,  # type: ignore[arg-type]
        kind='srs',
        title=title,
        subtitle=subtitle,
        lesson_type=None,
        eta_minutes=0 if completed_today and due_count <= 0 else _SRS_ITEM_ETA_MINUTES,
        url=build_slot_url('/study/cards?source=linear_plan', LinearSlotKind.SRS),
        completed=completed_today,
        completion_signal='srs_xp_earned',
        data=data,
    )
