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

import math
from datetime import datetime, timedelta
from typing import Any, Optional, Sequence

from sqlalchemy import func, or_

from app.srs.constants import MASTERED_THRESHOLD_DAYS, STATUS_REVIEW, CardState
from app.srs.visibility import naive_utc_now, srs_scope_filter, srs_servable_filter
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.utils.db import db as _db
from app.utils.db_utils import chunk_ids
from app.utils.time_utils import day_to_naive_utc


# Kept as a module-local alias: the normalisation itself now lives next to the
# visibility rule so both use one definition of "now" on the naive-UTC basis.
_naive_utc_now = naive_utc_now


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
            srs_servable_filter(user_id, now),
            UserCardDirection.state.in_(
                (
                    CardState.LEARNING.value,
                    CardState.RELEARNING.value,
                    CardState.REVIEW.value,
                )
            ),
            UserCardDirection.next_review <= now,
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
    user_word_ids_subq = db.session.query(UserWord.id).filter(
        UserWord.user_id == user_id,
        UserWord.srs_excluded.is_(False),
    )
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


# Recovery floor for mature reviews. ``TIER_PCT['collapse']`` sets the
# adaptive review percentage to 0.00, and low/critical round to 0 on a small
# ``reviews_per_day``, so the adaptive ceiling stops being a reduction and
# becomes a freeze: with a pure REVIEW backlog every consumer computed
# ``review_show = 0``, the SRS slot hit its early ``return None`` and vanished
# from the plan for the whole day, with no way in through /study either
# (DP-043). ``get_due_card_budget`` already promises this exact learner a
# "bounded-but-nonzero batch" so they can work the backlog down — this floor
# is what makes that promise true.
RECOVERY_REVIEW_FLOOR = 5


def get_review_batch_budget(
    user_id: int,
    db: Any = _db,
    now_utc: Optional[datetime] = None,
    *,
    remaining_reviews: Optional[int] = None,
    due_budget_left: Optional[int] = None,
) -> int:
    """How many REVIEW-state cards may still be served/shown today.

    The adaptive ceiling (``get_new_card_budget``'s second element) narrows
    mature reviews while the learner is struggling; the combined ceiling
    (``get_due_card_budget``) bounds learning + review together. When the
    adaptive ceiling has collapsed to zero, this falls back to a small fixed
    daily floor instead of zero — never above what the combined ceiling
    still allows.

    Pass ``remaining_reviews`` / ``due_budget_left`` when the caller already
    computed them (all daily-plan call sites do); they are only queried here
    when omitted.
    """
    if remaining_reviews is None:
        _, remaining_reviews = get_new_card_budget(user_id, db, now_utc=now_utc)
    if due_budget_left is None:
        due_budget_left = get_due_card_budget(user_id, db, now_utc=now_utc)

    if remaining_reviews > 0:
        allowance = remaining_reviews
    else:
        # Zero adaptive allowance: grant the recovery floor, minus whatever
        # of it today's reviews already consumed, so the batch stays bounded
        # across repeat visits within one day.
        reviews_today = count_reviews_today(user_id, db, now_utc=now_utc)
        allowance = max(0, RECOVERY_REVIEW_FLOOR - reviews_today)
    return max(0, min(allowance, due_budget_left))


# Lesson audit item 12 (2026-09-06). Learning/relearning used to take the whole
# combined ceiling first: the 20 directions a card lesson activates were all
# due the next day and left mature reviews with 0 of the 20 slots, so the
# review debt only grew on lesson days. This share of the day's remaining
# ceiling is held for REVIEW cards while any are due; learning takes the rest
# and anything the reserve does not need.
REVIEW_RESERVE_SHARE = 0.5


# Lesson audit item 13 (2026-09-06): how a day's review batch is composed.
# Mature cards overdue longer than ``OLD_DEBT_DAYS`` are «old debt»; the batch
# guarantees them ``OLD_DEBT_QUOTA_SHARE`` of its slots, fresh overdue cards
# take the rest, and whatever fresh cards do not fill goes to old debt. Dates
# are never rewritten: the debt shrinks by at least the quota every day while
# each session still opens with the cards that are easiest to recall.
OLD_DEBT_DAYS = 30
OLD_DEBT_QUOTA_SHARE = 1 / 3


def old_debt_cutoff(now_utc: datetime | None = None) -> datetime:
    """Naive-UTC moment before which a due REVIEW card counts as old debt."""
    return _naive_utc_now(now_utc) - timedelta(days=OLD_DEBT_DAYS)


def old_debt_quota(review_cap: int, old_available: int, fresh_available: int) -> tuple[int, int]:
    """Split ``review_cap`` slots into (fresh_take, old_take).

    Old debt keeps at least ``ceil(cap * share)`` slots (never more than there
    are old cards); fresh cards take the remainder; unused fresh slots fall
    back to old debt so the batch is always as full as the cards allow.
    """
    cap = max(0, int(review_cap))
    old_available = max(0, int(old_available))
    fresh_available = max(0, int(fresh_available))
    if cap == 0:
        return 0, 0
    old_min = min(old_available, math.ceil(cap * OLD_DEBT_QUOTA_SHARE))
    fresh_take = min(fresh_available, cap - old_min)
    old_take = min(old_available, cap - fresh_take)
    return fresh_take, old_take


def count_old_review_debt(user_id: int, db: Any = _db, now_utc: datetime | None = None) -> int:
    """Due REVIEW cards overdue longer than ``OLD_DEBT_DAYS`` (servable ones only)."""
    now = _naive_utc_now(now_utc)
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            srs_servable_filter(user_id, now),
            UserCardDirection.state == CardState.REVIEW.value,
            UserCardDirection.next_review < old_debt_cutoff(now),
        )
        .scalar() or 0
    )


def learning_budget_after_reserve(due_budget: int, review_pool: int) -> int:
    """Ceiling left for learning/relearning once the mature-review reserve is held.

    ``review_pool`` must be the number of review cards the *caller* can
    actually serve (its own time window and exclusions), not a global count:
    a reserve held for cards the queue will never hand out leaves half the
    budget idle (Codex review of item 12).
    """
    due_budget = max(0, int(due_budget))
    if due_budget <= 0:
        return 0
    reserve = min(max(0, int(review_pool)), math.ceil(due_budget * REVIEW_RESERVE_SHARE))
    return max(0, due_budget - reserve)


def split_due_budget(
    user_id: int,
    db: Any = _db,
    now_utc: datetime | None = None,
    *,
    learning_due: int,
    review_due: int,
    due_budget: int,
    remaining_reviews: int,
) -> tuple[int, int]:
    """How many (learning+relearning, mature review) cards fit into today.

    Single split used by the plan tile, the /study queue, the session
    completion check and the slot completion check: they must agree or the
    slot never closes / the tile promises cards the queue refuses.

    ``due_budget`` is the combined ceiling left today (``get_due_card_budget``),
    ``remaining_reviews`` the adaptive review allowance left
    (``get_new_card_budget()[1]``; equal to the base since item 12).
    """
    due_budget = max(0, int(due_budget))
    learning_due = max(0, int(learning_due))
    review_due = max(0, int(review_due))
    learning_show = min(learning_due, learning_budget_after_reserve(due_budget, review_due))
    review_show = min(
        review_due,
        get_review_batch_budget(
            user_id, db, now_utc=now_utc,
            remaining_reviews=remaining_reviews,
            due_budget_left=max(0, due_budget - learning_show),
        ),
    )
    return learning_show, review_show


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
            srs_servable_filter(user_id, now),
            UserCardDirection.state.in_(tuple(states)),
            UserCardDirection.next_review <= now,
        )
        .scalar() or 0
    )


def count_pending_new(user_id: int, db: Any = _db, now_utc: Optional[datetime] = None) -> int:
    """Count NEW-state directions the user can actually pick up today.

    These are not «due now» (NEW has no scheduling), they form the new-card
    pool the user can start within the ``new_words_per_day`` budget.

    The ``next_review`` bound matches what the /study queue serves. Without it
    the plan advertised cards the session refused to hand out: book vocab pull
    creates NEW cards dated tomorrow, and they were counted as available today.
    """
    end_of_today = day_to_naive_utc(user_id, db, days_ahead=1, now_utc=now_utc)
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            srs_servable_filter(user_id, now_utc),
            UserCardDirection.state == CardState.NEW.value,
            or_(
                UserCardDirection.next_review.is_(None),
                UserCardDirection.next_review < end_of_today,
            ),
        )
        .scalar() or 0
    )


def mastered_word_ids_subquery(user_id: int, db: Any = _db):
    """Subquery of word ids the user has mastered.

    "Mastered" is a threshold on top of ``status == 'review'`` (the shortest
    interval across both directions reaching ``MASTERED_THRESHOLD_DAYS``), never
    a stored status — ``recalculate_status`` cannot produce one. Filters written
    as ``UserWord.status == 'mastered'`` therefore matched nothing and silently
    returned empty lists and zero buckets.
    """
    return (
        db.session.query(UserWord.word_id)
        .join(UserCardDirection, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            srs_scope_filter(user_id),
            UserWord.status == STATUS_REVIEW,
        )
        .group_by(UserWord.word_id)
        .having(func.min(UserCardDirection.interval) >= MASTERED_THRESHOLD_DAYS)
    )


def count_resting_words(user_id: int, db: Any = _db, now_utc: Optional[datetime] = None) -> int:
    """Count distinct words currently resting for at least the rest of today.

    A resting word is one the SRS has taken out of circulation because it would
    not stick — see ``app/srs/scheduling.py``. Counting distinct words (rather
    than directions) means a word rested in both directions shows up once.

    The threshold is tomorrow's local midnight so the short intra-session bury
    (``UserCardDirection.bury_for_session``) is not reported as a rest. Note it
    deliberately selects buried rows, so it takes the scope half of the
    visibility rule only.
    """
    tomorrow_start = day_to_naive_utc(user_id, db, days_ahead=1, now_utc=now_utc)
    return int(
        db.session.query(func.count(func.distinct(UserCardDirection.user_word_id)))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            srs_scope_filter(user_id),
            UserCardDirection.buried_until.isnot(None),
            UserCardDirection.buried_until >= tomorrow_start,
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
    user_word_ids_subq = db.session.query(UserWord.id).filter(
        UserWord.user_id == user_id,
        UserWord.srs_excluded.is_(False),
    )
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
            UserWord.srs_excluded.is_(False),
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
