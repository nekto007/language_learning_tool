"""Canonical SRS counting and budget functions.

Single source of truth for due-card counts and daily-budget math across
mission-plan (`app/daily_plan/assembler.py`), linear-plan
(`app/daily_plan/linear/slots/srs_slot.py`) and the /study card API
(`app/study/api_routes.py`).

Design:
- All DateTime columns (`next_review`, `first_reviewed`, `last_reviewed`)
  are naive UTC. We normalize `now` to naive UTC before comparison.
- `count_due_cards` includes `UserCardDirection.state IN (learning,
  relearning, review)` and excludes buried cards. It deliberately does NOT
  filter on the derived `UserWord.status` (that field lags direction grades
  and caused counter drift). No mix filter — we count all due cards.
- `today_start` is the user's local-day midnight projected to naive UTC
  (matches XP/StreakEvent idempotency, prevents UTC-boundary skew).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, or_

from app.srs.constants import CardState
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.utils.db import db as _db
from app.utils.db_utils import chunk_ids
from app.utils.time_utils import day_to_naive_utc


def _naive_utc_now(now_utc: Optional[datetime] = None) -> datetime:
    if now_utc is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if now_utc.tzinfo is not None:
        return now_utc.astimezone(timezone.utc).replace(tzinfo=None)
    return now_utc


def _today_start_naive(user_id: int, db: Any = _db, now_utc: Optional[datetime] = None) -> datetime:
    return day_to_naive_utc(user_id, db, days_ahead=0, now_utc=now_utc)


def count_due_cards(
    user_id: int,
    db: Any = _db,
    now_utc: Optional[datetime] = None,
    word_ids: Optional[Sequence[int]] = None,
) -> int:
    """Count review/learning/relearning cards due for the user right now.

    Includes all three due states. Excludes NEW state (not yet activated)
    and currently-buried cards. Filters match `_get_due_cards` in
    `app/srs/service.py` — counter must reflect what gets actually served.

    `UserCardDirection.state` is authoritative; `UserWord.status` is a
    derived UI label updated by `recalculate_status` after grading. Filtering
    on the derived field hid cards whose parent status lagged behind a
    direction grade (race or partial cleanup), so the counter drifted from
    the queue. We trust the direction state directly.

    When ``word_ids`` is provided, restrict the count to cards whose underlying
    CollectionWord id is in that set — used by the mission assembler so its
    SRS-phase allocation matches what ``/study?source=daily_plan_mix`` can
    actually serve. ``None`` counts all due cards the user has.
    """
    now = _naive_utc_now(now_utc)
    query = (
        db.session.query(func.count(UserCardDirection.id))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.state.in_(
                (
                    CardState.LEARNING.value,
                    CardState.RELEARNING.value,
                    CardState.REVIEW.value,
                )
            ),
            UserCardDirection.next_review <= now,
            or_(
                UserCardDirection.buried_until.is_(None),
                UserCardDirection.buried_until <= now,
            ),
        )
    )
    if word_ids is not None:
        if not word_ids:
            return 0
        word_ids_list = list(word_ids)
        if len(word_ids_list) <= 1000:
            return int(query.filter(UserWord.word_id.in_(word_ids_list)).scalar() or 0)
        total = 0
        for chunk in chunk_ids(word_ids_list):
            total += int(query.filter(UserWord.word_id.in_(chunk)).scalar() or 0)
        return total
    return int(query.scalar() or 0)


def count_new_cards_today(user_id: int, db: Any = _db, now_utc: Optional[datetime] = None) -> int:
    """Count card directions first reviewed today (user-local day boundary)."""
    today_start = _today_start_naive(user_id, db, now_utc)
    user_word_ids_subq = db.session.query(UserWord.id).filter_by(user_id=user_id)
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .filter(
            UserCardDirection.user_word_id.in_(user_word_ids_subq),
            UserCardDirection.first_reviewed.isnot(None),
            UserCardDirection.first_reviewed >= today_start,
        )
        .scalar()
        or 0
    )


def get_new_card_budget(
    user_id: int, db: Any = _db, now_utc: Optional[datetime] = None
) -> tuple[int, int]:
    """Canonical daily budget: (remaining_new, remaining_reviews).

    Adaptive limits from `SRSService.get_adaptive_limits()` are the single
    source of truth — they already reduce the new-card ceiling when a user
    is struggling (accuracy < 85% or backlog > 50). Mission-plan, linear-plan
    and /study all route through this function to avoid drift.

    Results are clamped to ≥ 0.
    """
    from app.study.services import SRSService

    adaptive_new, adaptive_reviews = SRSService.get_adaptive_limits(user_id)
    new_today = count_new_cards_today(user_id, db, now_utc=now_utc)
    rev_today = count_reviews_today(user_id, db, now_utc=now_utc)
    return (
        max(0, adaptive_new - new_today),
        max(0, adaptive_reviews - rev_today),
    )


def get_due_card_budget(user_id: int, db: Any = _db, now_utc: Optional[datetime] = None) -> int:
    """Combined daily ceiling for *due* cards (RELEARNING + LEARNING + REVIEW).

    Uses the user's BASE ``reviews_per_day`` setting — NOT the adaptive
    reduction — on purpose:
      * the daily due-card session stays bounded (no unbounded learning pile
        that lets a struggling user drown in debt forever), and
      * a struggling user (collapse tier, where adaptive reviews → 0) still
        gets a bounded-but-nonzero batch and can work the backlog down, instead
        of being frozen out of recovery entirely.

    Subtracts review-type cards already done today (same metric as
    ``count_reviews_today``). Clamped to ≥ 0. Read-only on StudySettings
    (no auto-create — avoids committing a fresh row inside a grade txn).
    """
    settings = StudySettings.query.filter_by(user_id=user_id).first()
    # Fall back to the model default (20) only when NO settings row exists yet,
    # so a row-less user isn't frozen out of due cards with a 0 budget
    # (audit E-022). An explicit reviews_per_day=0 (user opted out) is respected.
    # Read-only — still no auto-create inside a grade txn.
    if settings is None:
        base_reviews = 20  # StudySettings.reviews_per_day model default
    else:
        base_reviews = settings.reviews_per_day or 0
    rev_today = count_reviews_today(user_id, db, now_utc=now_utc)
    return max(0, base_reviews - rev_today)


def count_due_by_states(
    user_id: int,
    db: Any = _db,
    states: Sequence[str] = (),
    now_utc: Optional[datetime] = None,
) -> int:
    """Count due directions filtered to specific SM-2 states.

    Used by SRS-slot UI to split «N новых · L в изучении · R на повтор»
    without rebuilding the same JOIN/where in three places.
    """
    if not states:
        return 0
    now = _naive_utc_now(now_utc)
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.state.in_(tuple(states)),
            UserCardDirection.next_review <= now,
            or_(
                UserCardDirection.buried_until.is_(None),
                UserCardDirection.buried_until <= now,
            ),
        )
        .scalar() or 0
    )


def count_pending_new(user_id: int, db: Any = _db) -> int:
    """Count NEW-state directions (started but never graded).

    These are not «due now» (NEW has no scheduling), they form the new-card
    pool the user can pick up within ``new_words_per_day`` budget.
    """
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.state == CardState.NEW.value,
        )
        .scalar() or 0
    )


def count_reviews_today(user_id: int, db: Any = _db, now_utc: Optional[datetime] = None) -> int:
    """Count card reviews that happened today excluding first-time reviews.

    NOTE (audit E-023): a card first seen today (first_reviewed >= today_start)
    is intentionally NOT counted even if it cycled NEW→LEARNING→REVIEW and was
    re-graded the same day. This is by design — the daily review cap governs
    cards carried over from prior days; same-day churn of freshly-activated
    cards is expected and not double-counted against the cap.
    """
    today_start = _today_start_naive(user_id, db, now_utc)
    user_word_ids_subq = db.session.query(UserWord.id).filter_by(user_id=user_id)
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .filter(
            UserCardDirection.user_word_id.in_(user_word_ids_subq),
            UserCardDirection.last_reviewed.isnot(None),
            UserCardDirection.last_reviewed >= today_start,
            UserCardDirection.first_reviewed.isnot(None),
            UserCardDirection.first_reviewed < today_start,
        )
        .scalar()
        or 0
    )


def get_review_forecast(
    user_id: int,
    days: int = 7,
    db: Any = _db,
    now_utc: Optional[datetime] = None,
) -> list:
    """Forecast of review-card counts per user-local day, starting today.

    Returns ``[{'date': 'YYYY-MM-DD', 'count': N}, ...]`` of length ``days``.
    Bucket 0 absorbs everything overdue (next_review in the past). A buried
    card lands in the bucket of ``max(next_review, buried_until)`` — that's
    when it actually becomes reviewable. Day boundaries come from
    ``day_to_naive_utc`` so the forecast matches the due-counters above.
    """
    from datetime import date as _date, timedelta

    from app.utils.time_utils import get_user_local_date

    if days <= 0:
        return []

    boundaries = [
        day_to_naive_utc(user_id, db, days_ahead=k, now_utc=now_utc)
        for k in range(1, days + 1)
    ]
    horizon = boundaries[-1]

    rows = (
        db.session.query(UserCardDirection.next_review, UserCardDirection.buried_until)
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.state.in_(
                (
                    CardState.LEARNING.value,
                    CardState.RELEARNING.value,
                    CardState.REVIEW.value,
                )
            ),
            UserCardDirection.next_review.isnot(None),
            UserCardDirection.next_review < horizon,
        )
        .all()
    )

    counts = [0] * days
    for next_review, buried_until in rows:
        effective = next_review
        if buried_until is not None and buried_until > effective:
            effective = buried_until
        for k, boundary in enumerate(boundaries):
            if effective < boundary:
                counts[k] += 1
                break

    local_today: _date = get_user_local_date(user_id, db)
    return [
        {'date': (local_today + timedelta(days=k)).isoformat(), 'count': counts[k]}
        for k in range(days)
    ]
