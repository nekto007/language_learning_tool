"""SRS/deck quiz slot — second baseline slot on the linear spine.

Universal daily pool model (Раздел 5 of docs/srs-fix-plan.md):
NEW + LEARNING/RELEARNING + REVIEW within the user's adaptive caps —
shared with ``app/daily_plan/items/srs.py::build_srs_item`` and the
``/study`` auto-mode path. Single source of truth lives in
``app/srs/counting.py``; this module only formats the result for the
legacy linear chain.

Special case: when the current curriculum slot is itself a card lesson,
``build_srs_slot`` returns a deck-quiz slot instead so the two card
activities don't satisfy each other.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, or_

logger = logging.getLogger(__name__)

from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.slots import LinearSlot
from app.srs.constants import CardState
from app.study.models import QuizDeck, QuizDeckWord
from app.words.models import CollectionWords

_SRS_SLOT_ETA_MINUTES = 8
_CARD_LESSON_TYPES = frozenset({'card', 'flashcards'})
_DECK_QUIZ_LIMIT = 30
_DECK_QUIZ_SOURCE = 'linear_plan_deck_quiz'


def count_srs_reviews_today(user_id: int, db: Any) -> int:
    """Count review cards done today using the same semantics as /study."""
    from app.srs.counting import count_reviews_today

    return count_reviews_today(user_id, db)


def _linear_srs_completed_today(user_id: int, db: Any) -> bool:
    """Return True when the linear SRS slot is done for today.

    Delegates to :func:`app.daily_plan.linear.xp.is_srs_slot_completed_today`
    so the primary StreakEvent check and the lost-XP fallback are
    consistent with ``build_srs_item``.
    """
    from app.daily_plan.linear.xp import is_srs_slot_completed_today

    return is_srs_slot_completed_today(user_id, db)


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
        logger.info("srs_slot user=%s mode=deck_quiz state=done_today words=%d", user_id, deck_word_count)
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
        logger.info("srs_slot user=%s mode=deck_quiz state=empty no_deck_words", user_id)
        return LinearSlot(
            kind='srs',
            title='Нет слов для квиза в колодах',
            lesson_type='quiz',
            eta_minutes=0,
            url=None,
            completed=True,
            data=data,
        )

    logger.info("srs_slot user=%s mode=deck_quiz state=pending words=%d limit=%d", user_id, deck_word_count, limit)
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
    """Build the SRS baseline slot for the linear chain.

    Universal daily pool (Раздел 5): NEW + LEARNING/RELEARNING + REVIEW
    within the user's adaptive caps. Same model and counting helpers as
    ``app/daily_plan/items/srs.py::build_srs_item`` — only the output
    type differs (LinearSlot vs PlanItem) for the legacy chain consumer.
    """
    if getattr(curriculum_lesson, 'type', None) in _CARD_LESSON_TYPES:
        return _build_deck_quiz_slot(user_id, db)

    from app.srs.counting import (
        count_due_by_states,
        count_new_cards_today,
        count_pending_new,
        count_reviews_today,
        get_due_card_budget,
        get_new_card_budget,
    )
    from app.study.services import SRSService

    new_pending = count_pending_new(user_id, db)
    learning_due = count_due_by_states(
        user_id, db, states=(CardState.LEARNING.value, CardState.RELEARNING.value),
    )
    review_due = count_due_by_states(user_id, db, states=(CardState.REVIEW.value,))

    remaining_new, remaining_reviews = get_new_card_budget(user_id, db)
    # Combined daily ceiling across learning/relearning/review (base reviews_per_day).
    # Learning/relearning get priority over mature review; new keeps its own budget.
    due_budget = get_due_card_budget(user_id, db)
    new_show = min(new_pending, remaining_new)
    learning_show = min(learning_due, due_budget)
    review_show = min(review_due, max(0, due_budget - learning_show), remaining_reviews)
    total_show = new_show + learning_show + review_show

    new_today = count_new_cards_today(user_id, db)
    reviews_today_total = count_reviews_today(user_id, db)
    tier = SRSService.get_adaptive_limit_reason(user_id)
    completed_today = _linear_srs_completed_today(user_id, db)

    data = {
        'new_show': new_show,
        'learning_due': learning_due,
        'learning_show': learning_show,
        'review_show': review_show,
        'total_show': total_show,
        'new_pending': new_pending,
        'review_due': review_due,
        'new_today': new_today,
        'reviews_today': reviews_today_total,
        'remaining_new': remaining_new,
        'remaining_reviews': remaining_reviews,
        'srs_tier': tier,
    }

    if total_show > 0:
        logger.info(
            "srs_slot user=%s state=pending total=%d new=%d learning=%d review=%d tier=%s",
            user_id, total_show, new_show, learning_due, review_show, tier,
        )
        subtitle_bits = []
        if new_show > 0:
            subtitle_bits.append(f'{new_show} новых')
        if learning_show > 0:
            subtitle_bits.append(f'{learning_show} в изучении')
        if review_show > 0:
            subtitle_bits.append(f'{review_show} на повтор')
        return LinearSlot(
            kind='srs',
            title=f'Повторение слов — {total_show}',
            lesson_type=None,
            eta_minutes=_SRS_SLOT_ETA_MINUTES,
            url=build_slot_url('/study/cards?source=linear_plan', LinearSlotKind.SRS),
            completed=False,
            data=data,
        )

    if completed_today:
        title = 'Повторение закрыто'
        state = 'done_today'
    elif review_due > 0 and remaining_reviews == 0:
        title = 'Лимит повторений на сегодня достигнут'
        state = 'limit_reached'
    else:
        title = 'Сегодня повторять нечего'
        state = 'nothing_due'
    logger.info(
        "srs_slot user=%s state=%s new_pending=%d review_due=%d remaining_reviews=%d",
        user_id, state, new_pending, review_due, remaining_reviews,
    )
    return LinearSlot(
        kind='srs',
        title=title,
        lesson_type=None,
        eta_minutes=0,
        url=None,
        completed=True,
        data=data,
    )
