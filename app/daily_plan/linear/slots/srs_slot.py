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
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _user_word_ids_subquery(user_id: int, db: Any):
    return db.session.query(UserWord.id).filter(UserWord.user_id == user_id)


def get_srs_budget_remaining(user_id: int, db: Any) -> int:
    """Return remaining daily new-card budget for the user.

    Delegates to the canonical `get_new_card_budget` (adaptive-limits source
    of truth shared by mission-plan, linear-plan and /study). Returns only
    the new-card half — review budget is tracked separately in this slot.
    """
    from app.srs.counting import get_new_card_budget

    remaining_new, _ = get_new_card_budget(user_id, db)
    return remaining_new


def count_srs_due_cards(user_id: int, db: Any) -> int:
    """Count review/learning/relearning cards due for the user right now."""
    from app.srs.counting import count_due_cards

    return count_due_cards(user_id, db)


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
    from app.srs.counting import count_reviews_today

    return count_reviews_today(user_id, db)


def count_linear_plan_srs_due_cards(user_id: int, db: Any) -> int:
    """Count cards the linear-plan SRS slot can actually serve today."""
    settings = StudySettings.get_settings(user_id)
    reviews_limit = max(int(settings.reviews_per_day or 0), 0)
    reviews_today = count_srs_reviews_today(user_id, db)
    reviews_remaining = max(reviews_limit - reviews_today, 0)
    backlog_due_count = count_srs_due_cards(user_id, db)
    return min(backlog_due_count, reviews_remaining)


def _linear_srs_completed_today(user_id: int, db: Any) -> bool:
    """Return whether the linear SRS/global study slot has awarded XP today."""
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import (
        LINEAR_XP_EVENT_TYPE,
        get_linear_event_local_date,
    )

    today = get_linear_event_local_date(user_id, db)
    query = db.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.event_date == today,
        StreakEvent.details['source'].astext == 'linear_srs_global',
    )
    return db.session.query(query.exists()).scalar() or False


def _count_user_deck_quiz_words(user_id: int, db: Any) -> int:
    valid_custom_word = and_(
        QuizDeckWord.custom_english.isnot(None),
        QuizDeckWord.custom_english != '',
        QuizDeckWord.custom_russian.isnot(None),
        QuizDeckWord.custom_russian != '',
    )
    valid_collection_word = and_(
        QuizDeckWord.word_id.isnot(None),
        CollectionWords.english_word.isnot(None),
        CollectionWords.english_word != '',
        CollectionWords.russian_word.isnot(None),
        CollectionWords.russian_word != '',
    )
    rows = (
        db.session.query(
            QuizDeckWord.word_id,
            QuizDeckWord.custom_english,
            QuizDeckWord.custom_russian,
        )
        .join(QuizDeck, QuizDeckWord.deck_id == QuizDeck.id)
        .outerjoin(CollectionWords, QuizDeckWord.word_id == CollectionWords.id)
        .filter(
            QuizDeck.user_id == user_id,
            or_(valid_collection_word, valid_custom_word),
        )
        .all()
    )

    seen: set[object] = set()
    for word_id, custom_english, custom_russian in rows:
        key = (
            word_id
            if word_id is not None
            else ('custom', custom_english.strip().lower(), custom_russian.strip().lower())
        )
        seen.add(key)
    return len(seen)


def _build_deck_quiz_slot(user_id: int, db: Any) -> LinearSlot:
    deck_word_count = _count_user_deck_quiz_words(user_id, db)
    completed = _linear_srs_completed_today(user_id, db)
    limit = min(_DECK_QUIZ_LIMIT, max(deck_word_count, 0))
    data = {
        'mode': 'deck_quiz',
        'source': _DECK_QUIZ_SOURCE,
        'deck_word_count': deck_word_count,
        'word_limit': limit,
        'completed_today': completed,
    }

    if completed:
        return LinearSlot(
            kind='srs',
            title='Квиз по словам из колод готов',
            lesson_type='quiz',
            eta_minutes=0,
            url=None,
            completed=True,
            data=data,
        )

    if deck_word_count <= 0:
        return LinearSlot(
            kind='srs',
            title='Нет слов для квиза в колодах',
            lesson_type='quiz',
            eta_minutes=0,
            url=None,
            completed=True,
            data=data,
        )

    return LinearSlot(
        kind='srs',
        title='Квиз по словам из колод',
        lesson_type='quiz',
        eta_minutes=_SRS_SLOT_ETA_MINUTES,
        url=build_slot_url(
            f'/study/quiz/linear-plan?source={_DECK_QUIZ_SOURCE}&limit={limit}',
            LinearSlotKind.SRS,
        ),
        completed=False,
        data=data,
    )


def build_srs_slot(user_id: int, db: Any, curriculum_lesson: Any = None) -> LinearSlot:
    """Build the SRS baseline slot for the dashboard.

    Active when ``due_count > 0``. When there is nothing due, the slot
    collapses to a completed placeholder — "review tomorrow" if the user
    touched any cards today, "nothing due" otherwise.
    """
    if getattr(curriculum_lesson, 'type', None) in _CARD_LESSON_TYPES:
        return _build_deck_quiz_slot(user_id, db)

    settings = StudySettings.get_settings(user_id)
    reviews_limit = max(int(settings.reviews_per_day or 0), 0)
    reviews_today = count_srs_reviews_today(user_id, db)
    reviews_remaining = max(reviews_limit - reviews_today, 0)
    backlog_due_count = count_srs_due_cards(user_id, db)
    due_count = count_linear_plan_srs_due_cards(user_id, db)
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


def get_linear_plan_due_mix_cards(user_id: int, db: Any, limit: int) -> list[dict]:
    """Return due cards for the card-lesson mix injected by linear plan."""
    if limit <= 0:
        return []

    from app.curriculum.routes.card_lessons import _build_cards_for_words

    now = datetime.now(timezone.utc)
    due_directions = (
        db.session.query(UserCardDirection)
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

    due_direction_ids = {direction.id for direction in due_directions}
    return [card for card in cards if card.get('direction_id') in due_direction_ids]
