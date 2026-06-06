"""Canonical SRS review scheduling.

Single source of truth for writing the time-based fields of a card after an
SM-2 grade: ``last_reviewed``, ``first_reviewed``, ``buried_until`` (+ the
``consecutive_leech_burials`` streak counter) and ``next_review``.

Both grading surfaces delegate here so they stay byte-identical:
- ``UnifiedSRSService.grade_card`` (``app/srs/service.py``)
- ``UserCardDirection.update_after_review`` (``app/study/models.py``)

Time basis — **user-local-day midnight projected to naive UTC**
(``day_to_naive_utc``). Counters in ``app/srs/counting.py`` compare against the
same local-day boundary, so scheduling must anchor to it too; otherwise a card
graded via the daily-plan paths (which used to write a raw UTC instant) would
become due at a different wall-clock time than one graded via the curriculum
SRS path. Intra-day learning steps that cross local midnight are pushed to the
next day via ``minutes_to_day_offset``.

The SM-2 *math* itself (state/step/interval/ease/lapses/repetitions and the
``bury_days``/``requeue_minutes``/``days_until_review`` signals) lives in
``UnifiedSRSService.calculate_sm2_update`` — callers must apply that result to
the card *before* calling this helper, because ``next_review`` branches on the
card's new ``state``.
"""
from __future__ import annotations

import random
from typing import Any, Dict

from app.srs.constants import (
    CardState,
    MAX_REVIEW_INTERVAL_DAYS,
    RATING_DOUBT,
)
from app.utils.time_utils import day_to_naive_utc, minutes_to_day_offset


def apply_review_schedule(
    card: Any,
    update_result: Dict[str, Any],
    *,
    rating: int,
    is_first_review: bool,
    user_id: int,
    db: Any,
) -> None:
    """Write day-anchored review timestamps onto ``card`` after an SM-2 grade.

    Mutates ``card`` in place. Assumes ``card.state`` already reflects the
    post-grade state from ``update_result``. Does NOT touch SM-2 fields,
    correct/incorrect counters, ``session_attempts`` or the parent UserWord
    status — those remain the caller's responsibility.

    Args:
        card: UserCardDirection being graded.
        update_result: dict returned by ``calculate_sm2_update`` — read for
            ``bury_days``, ``requeue_minutes`` and ``days_until_review``.
        rating: the rating applied (1/2/3) — needed for the leech-bury reset.
        is_first_review: True when this is the card's first-ever grade (the
            caller must capture ``card.first_reviewed is None`` *before*
            mutating the card).
        user_id: owner id — resolves the local timezone for day anchoring.
        db: SQLAlchemy session/handle passed through to the time helpers.
    """
    today_midnight = day_to_naive_utc(user_id, db, days_ahead=0)
    card.last_reviewed = today_midnight
    if is_first_review:
        card.first_reviewed = today_midnight

    bury_days = update_result.get('bury_days')
    if bury_days:
        card.buried_until = day_to_naive_utc(user_id, db, days_ahead=bury_days)
        # Progressive leech bury: track consecutive burials without an
        # intervening successful review.
        card.consecutive_leech_burials = (card.consecutive_leech_burials or 0) + 1
    elif (
        card.state == CardState.REVIEW.value
        and rating >= RATING_DOUBT
    ):
        # Successful review — break the leech-bury streak so the next bury
        # (if any) restarts from the base interval.
        card.consecutive_leech_burials = 0

    requeue_minutes = update_result.get('requeue_minutes')
    days_until_review = update_result.get('days_until_review', 0) or 0

    if card.state == CardState.REVIEW.value and days_until_review > 0:
        # Add ±10% variance to prevent review cliffs, then re-cap so variance
        # can't push us past MAX_REVIEW_INTERVAL_DAYS.
        variance = random.uniform(0.9, 1.1)
        adjusted_days = max(1, round(days_until_review * variance))
        adjusted_days = min(MAX_REVIEW_INTERVAL_DAYS, adjusted_days)
        card.next_review = day_to_naive_utc(user_id, db, days_ahead=adjusted_days)
    elif requeue_minutes:
        # Intra-day learning steps stay today (session re-queue handles
        # in-session order); steps that cross local midnight schedule for the
        # next day.
        day_offset = minutes_to_day_offset(user_id, db, minutes=requeue_minutes)
        card.next_review = day_to_naive_utc(user_id, db, days_ahead=day_offset)
    else:
        card.next_review = today_midnight
