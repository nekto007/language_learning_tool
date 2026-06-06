"""SRS-slot completion must not be blocked by a just-stepped learning card
(finding #11).

A card graded into a sub-day learning step is scheduled for the real
near-future minute (now + step), so it is NOT "due" backlog. The completion
pool (shared by the /study complete-session gate, the corrective
``is_srs_slot_completed_today`` path, and ``build_srs_item``) must therefore
treat the slot as cleared when nothing else remains.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.srs.constants import CardState, RATING_DONT_KNOW
from app.daily_plan.linear.xp import is_srs_slot_completed_today
from app.srs.counting import count_due_by_states
from app.study.models import UserCardDirection, UserWord
from app.utils.db import db as app_db
from app.words.models import CollectionWords


def _make_new_card(db_session, user_id: int) -> UserCardDirection:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'slot_{suffix}',
        russian_word=f'slot_ru_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.flush()

    uw = UserWord(user_id=user_id, word_id=word.id)
    uw.status = 'new'
    db_session.add(uw)
    db_session.flush()

    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = CardState.NEW.value
    card.next_review = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(card)
    db_session.commit()
    return card


def test_just_stepped_learning_card_does_not_block_slot(db_session, test_user):
    card = _make_new_card(db_session, test_user.id)

    # NEW + DONT_KNOW → LEARNING step 0 (1-min step). After the fix next_review
    # is now + 1min (future), so it is NOT counted as due.
    card.update_after_review(RATING_DONT_KNOW)
    db_session.commit()

    assert card.state == CardState.LEARNING.value
    # The freshly-stepped card must not register as due backlog.
    due_learning = count_due_by_states(
        test_user.id, app_db,
        states=(CardState.LEARNING.value, CardState.RELEARNING.value),
    )
    assert due_learning == 0

    # Slot is considered done (corrective award fires): the user graded a card
    # today and nothing else is due. Before the fix the card was snapped to
    # local midnight (due) and this returned False.
    assert is_srs_slot_completed_today(test_user.id, app_db) is True
