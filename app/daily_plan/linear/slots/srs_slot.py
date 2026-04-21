"""SRS global review slot — second baseline slot on the linear spine.

Exposes the remaining new-card budget and the due-card queue for the
user's personal decks (/study), plus a helper that builds the "mix" of
due cards injected into a curriculum card-lesson when the user opens it
via ``?source=linear_plan_card`` (see ``app/curriculum/routes/card_lessons.py``).

Budget semantics:
- ``budget = max_new_per_day - first_reviewed_today_count``
- ``max_new_per_day`` is ``StudySettings.new_words_per_day`` — the same
  source /study uses, so linear and /study share one daily budget.

Slot states:
- due > 0 → active, links to ``/study?source=linear_plan``.
- due = 0 AND any card reviewed today → collapsed "review tomorrow", completed.
- due = 0 AND no activity today → collapsed "nothing due today", completed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_

from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.slots import LinearSlot
from app.srs.constants import CardState
from app.study.models import StudySettings, UserCardDirection, UserWord


_SRS_SLOT_ETA_MINUTES = 8


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _user_word_ids_subquery(user_id: int, db: Any):
    return db.session.query(UserWord.id).filter(UserWord.user_id == user_id)


def get_srs_budget_remaining(user_id: int, db: Any) -> int:
    """Return remaining daily new-card budget for the user.

    Reads ``max_new_per_day`` from ``StudySettings`` (the same knob /study
    uses) and subtracts the count of ``UserCardDirection`` rows whose
    ``first_reviewed`` is today. Never returns a negative number.
    """
    settings = StudySettings.get_settings(user_id)
    max_new = int(settings.new_words_per_day or 0)

    start = _today_start()
    used_today = (
        db.session.query(func.count(UserCardDirection.id))
        .filter(
            UserCardDirection.user_word_id.in_(_user_word_ids_subquery(user_id, db)),
            UserCardDirection.first_reviewed.isnot(None),
            UserCardDirection.first_reviewed >= start,
        )
        .scalar()
        or 0
    )
    return max(max_new - int(used_today), 0)


def count_srs_due_cards(user_id: int, db: Any) -> int:
    """Count review/learning/relearning cards due for the user right now."""
    now = datetime.now(timezone.utc)
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .filter(
            UserCardDirection.user_word_id.in_(_user_word_ids_subquery(user_id, db)),
            UserCardDirection.next_review <= now,
            or_(
                UserCardDirection.buried_until.is_(None),
                UserCardDirection.buried_until <= now,
            ),
            UserCardDirection.state.in_(
                (
                    CardState.LEARNING.value,
                    CardState.RELEARNING.value,
                    CardState.REVIEW.value,
                )
            ),
        )
        .scalar()
        or 0
    )


def count_srs_cards_studied_today(user_id: int, db: Any) -> int:
    """Count card directions the user reviewed today (any state)."""
    start = _today_start()
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .filter(
            UserCardDirection.user_word_id.in_(_user_word_ids_subquery(user_id, db)),
            UserCardDirection.last_reviewed.isnot(None),
            UserCardDirection.last_reviewed >= start,
        )
        .scalar()
        or 0
    )


def build_srs_slot(user_id: int, db: Any) -> LinearSlot:
    """Build the SRS baseline slot for the dashboard.

    Active when ``due_count > 0``. When there is nothing due, the slot
    collapses to a completed placeholder — "review tomorrow" if the user
    touched any cards today, "nothing due" otherwise.
    """
    due_count = count_srs_due_cards(user_id, db)
    studied_today = count_srs_cards_studied_today(user_id, db)
    budget_remaining = get_srs_budget_remaining(user_id, db)

    data = {
        'due_count': due_count,
        'studied_today': studied_today,
        'budget_remaining': budget_remaining,
    }

    if due_count > 0:
        return LinearSlot(
            kind='srs',
            title=f'Повторить {due_count} карточек',
            lesson_type=None,
            eta_minutes=_SRS_SLOT_ETA_MINUTES,
            url=build_slot_url('/study?source=linear_plan', LinearSlotKind.SRS),
            completed=False,
            data=data,
        )

    title = 'Карточки повторим завтра' if studied_today > 0 else 'Сегодня повторять нечего'
    return LinearSlot(
        kind='srs',
        title=title,
        lesson_type=None,
        eta_minutes=0,
        url=None,
        completed=True,
        data=data,
    )


def get_linear_plan_due_mix_cards(user_id: int, db: Any, limit: int) -> list[dict]:
    """Return due cards formatted for the card-lesson mix injected into
    a curriculum card lesson opened via ``?source=linear_plan_card``.

    Ordered by ``next_review`` ascending (oldest due first). Returns up to
    ``limit`` cards; callers pass ``min(budget, 10)`` to bound the session.
    Returns ``[]`` when the user has no due cards.
    """
    if limit <= 0:
        return []

    from app.curriculum.routes.card_lessons import _build_cards_for_words
    from app.words.models import CollectionWords

    now = datetime.now(timezone.utc)

    due_directions = (
        db.session.query(UserCardDirection)
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.next_review <= now,
            or_(
                UserCardDirection.buried_until.is_(None),
                UserCardDirection.buried_until <= now,
            ),
            UserCardDirection.state.in_(
                (
                    CardState.LEARNING.value,
                    CardState.RELEARNING.value,
                    CardState.REVIEW.value,
                )
            ),
        )
        .order_by(UserCardDirection.next_review.asc())
        .limit(limit)
        .all()
    )
    if not due_directions:
        return []

    word_ids = []
    seen: set[int] = set()
    for direction in due_directions:
        word_id = direction.user_word.word_id if direction.user_word is not None else None
        if word_id and word_id not in seen:
            seen.add(word_id)
            word_ids.append(word_id)

    if not word_ids:
        return []

    word_objects = CollectionWords.query.filter(CollectionWords.id.in_(word_ids)).all()
    cards = _build_cards_for_words(word_objects, user_id, activate_srs=False)

    # Keep only cards that correspond to actually-due direction ids so we
    # don't leak the opposite direction (e.g. rus-eng when only eng-rus is due).
    due_direction_ids = {d.id for d in due_directions}
    mix_cards = [c for c in cards if c.get('direction_id') in due_direction_ids]
    return mix_cards
