"""SRS/deck quiz slot — second baseline slot on the linear spine.

Usually exposes the due-card queue for the user's personal decks (/study).
When the current curriculum slot is itself a card lesson, this slot becomes
a deck quiz so the same card session does not satisfy both baseline tasks.

Budget semantics:
- ``budget = max_new_per_day - first_reviewed_today_count``
- ``max_new_per_day`` is ``StudySettings.new_words_per_day`` — the same
  source /study uses, so linear and /study share one daily budget.

Slot states:
- due > 0 → active, links directly to ``/study/cards?source=linear_plan``.
- due = 0 AND any card reviewed today → collapsed "review tomorrow", completed.
- due = 0 AND no activity today → collapsed "nothing due today", completed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, func, or_

from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.slots import LinearSlot
from app.srs.constants import CardState
from app.study.models import QuizDeck, QuizDeckWord, StudySettings, UserCardDirection, UserWord
from app.words.models import CollectionWords


_SRS_SLOT_ETA_MINUTES = 8
_CARD_LESSON_TYPES = frozenset({'card', 'flashcards'})
_DECK_QUIZ_LIMIT = 30
_DECK_QUIZ_SOURCE = 'linear_plan_deck_quiz'


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
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserWord.status.in_(('new', 'learning', 'review')),
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


def count_srs_reviews_today(user_id: int, db: Any) -> int:
    """Count review cards done today using the same semantics as /study."""
    start = _today_start()
    return int(
        db.session.query(func.count(UserCardDirection.id))
        .filter(
            UserCardDirection.user_word_id.in_(_user_word_ids_subquery(user_id, db)),
            UserCardDirection.last_reviewed.isnot(None),
            UserCardDirection.last_reviewed >= start,
            UserCardDirection.first_reviewed.isnot(None),
            UserCardDirection.first_reviewed < start,
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
    settings = StudySettings.get_settings(user_id)
    reviews_limit = max(int(settings.reviews_per_day or 0), 0)
    reviews_today = count_srs_reviews_today(user_id, db)
    reviews_remaining = max(reviews_limit - reviews_today, 0)

    backlog_due_count = count_srs_due_cards(user_id, db)
    due_count = min(backlog_due_count, reviews_remaining)
    studied_today = count_srs_cards_studied_today(user_id, db)
    budget_remaining = get_srs_budget_remaining(user_id, db)

    data = {
        'due_count': due_count,
        'backlog_due_count': backlog_due_count,
        'studied_today': studied_today,
        'reviews_today': reviews_today,
        'reviews_limit': reviews_limit,
        'reviews_remaining': reviews_remaining,
        'budget_remaining': budget_remaining,
    }

    if due_count > 0:
        return LinearSlot(
            kind='srs',
            title=f'Повторить {due_count} карточек',
            lesson_type=None,
            eta_minutes=_SRS_SLOT_ETA_MINUTES,
            url=build_slot_url('/study/cards?source=linear_plan', LinearSlotKind.SRS),
            completed=False,
            data=data,
        )

    if backlog_due_count > 0 and reviews_remaining == 0:
        title = 'Лимит повторений на сегодня достигнут'
    else:
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
