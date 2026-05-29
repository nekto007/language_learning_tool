"""Tests for SRSService.get_card_counts canonical due counting (Task 5).

Verifies that after the Phase 2.a refactor:
- NEW-state cards are NOT included in due_count
- Cards with next_review in the future are NOT counted as due
- Cards with next_review in the past ARE counted
- Buried cards are NOT counted
- All paths delegate to count_due_cards from app/srs/counting.py
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.srs.constants import CardState, DEFAULT_EASE_FACTOR
from app.srs.counting import count_due_cards
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.study.services.srs_service import SRSService
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'gc_{suffix}',
        email=f'gc_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_word(db_session) -> CollectionWords:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'gcword_{suffix}',
        russian_word=f'gcслово_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.commit()
    return word


def _make_user_word(db_session, user: User, word: CollectionWords, *, status: str = 'learning') -> UserWord:
    uw = UserWord(user_id=user.id, word_id=word.id)
    uw.status = status
    db_session.add(uw)
    db_session.commit()
    return uw


def _make_direction(
    db_session,
    user_word: UserWord,
    *,
    state: str,
    next_review: datetime | None = None,
    first_reviewed: datetime | None = None,
    buried_until: datetime | None = None,
    direction: str = 'eng-rus',
) -> UserCardDirection:
    now = _now_naive()
    row = UserCardDirection(user_word_id=user_word.id, direction=direction)
    row.state = state
    row.next_review = next_review if next_review is not None else now
    row.first_reviewed = first_reviewed
    row.buried_until = buried_until
    row.ease_factor = DEFAULT_EASE_FACTOR
    row.repetitions = 0
    db_session.add(row)
    db_session.commit()
    return row


class TestGetCardCountsDueCounting:
    """SRSService.get_card_counts must not include NEW, future-due, or buried cards."""

    def test_new_card_not_counted_as_due(self, db_session):
        user = _make_user(db_session)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(db_session, uw, state=CardState.NEW.value, next_review=_now_naive() - timedelta(hours=1))

        result = SRSService.get_card_counts(user.id)
        assert result['due_count'] == 0

    def test_card_due_tomorrow_not_counted(self, db_session):
        user = _make_user(db_session)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=_now_naive() + timedelta(days=1),
        )

        result = SRSService.get_card_counts(user.id)
        assert result['due_count'] == 0

    def test_card_due_one_minute_ago_counted(self, db_session):
        user = _make_user(db_session)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=_now_naive() - timedelta(minutes=1),
        )

        result = SRSService.get_card_counts(user.id)
        assert result['due_count'] == 1

    def test_buried_card_not_counted(self, db_session):
        user = _make_user(db_session)
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=_now_naive() - timedelta(hours=1),
            buried_until=_now_naive() + timedelta(days=7),
        )

        result = SRSService.get_card_counts(user.id)
        assert result['due_count'] == 0

    def test_learning_and_relearning_states_counted(self, db_session):
        user = _make_user(db_session)
        now = _now_naive()
        for state in (CardState.LEARNING.value, CardState.RELEARNING.value):
            word = _make_word(db_session)
            uw = _make_user_word(db_session, user, word)
            _make_direction(
                db_session, uw,
                state=state,
                next_review=now - timedelta(minutes=5),
            )

        result = SRSService.get_card_counts(user.id)
        assert result['due_count'] == 2

    def test_due_count_matches_canonical_count_due_cards(self, db_session):
        """get_card_counts.due_count must equal count_due_cards for same user."""
        from app.utils.db import db as real_db

        user = _make_user(db_session)
        now = _now_naive()

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(minutes=5),
        )

        canonical = count_due_cards(user.id, real_db)
        result = SRSService.get_card_counts(user.id)
        assert result['due_count'] == canonical

    def test_deck_word_ids_restricts_due_count(self, db_session):
        """With deck_word_ids, due_count only includes cards from that set."""
        from app.utils.db import db as real_db

        user = _make_user(db_session)
        now = _now_naive()

        word_in = _make_word(db_session)
        word_out = _make_word(db_session)
        for w in (word_in, word_out):
            uw = _make_user_word(db_session, user, w)
            _make_direction(
                db_session, uw,
                state=CardState.REVIEW.value,
                next_review=now - timedelta(minutes=5),
            )

        result_all = SRSService.get_card_counts(user.id)
        result_deck = SRSService.get_card_counts(user.id, deck_word_ids=[word_in.id])

        assert result_all['due_count'] == 2
        assert result_deck['due_count'] == 1


class TestHasGuidedRecallContent:
    """_has_guided_recall_content must use count_due_cards directly (Task 5)."""

    def test_no_due_cards_no_new_returns_false(self, db_session):
        from app.daily_plan.assembler import _has_guided_recall_content
        from unittest.mock import patch

        user = _make_user(db_session)

        with patch('app.study.deck_utils.get_daily_plan_mix_word_ids', return_value=[]):
            result = _has_guided_recall_content(user.id)
        assert result is False

    def test_due_card_in_mix_returns_true(self, db_session):
        from app.daily_plan.assembler import _has_guided_recall_content
        from app.study.models import QuizDeck, QuizDeckWord
        from unittest.mock import patch

        user = _make_user(db_session)
        now = _now_naive()

        deck = QuizDeck(user_id=user.id, title='mix deck')
        db_session.add(deck)
        db_session.commit()

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.REVIEW.value,
            next_review=now - timedelta(minutes=5),
        )
        db_session.add(QuizDeckWord(deck_id=deck.id, word_id=word.id))
        db_session.commit()

        with patch('app.daily_plan.assembler.get_daily_plan_mix_word_ids', return_value=[word.id]):
            result = _has_guided_recall_content(user.id)
        assert result is True

    def test_new_card_not_due_does_not_cause_true_without_budget(self, db_session):
        """NEW-state card should not make _has_guided_recall_content return True
        when the new-card daily budget is already exhausted."""
        from app.daily_plan.assembler import _has_guided_recall_content
        from unittest.mock import patch

        user = _make_user(db_session)
        now = _now_naive()

        # No budget: create study settings with limit=0 today
        settings = StudySettings(user_id=user.id)
        settings.new_words_per_day = 0
        settings.reviews_per_day = 20
        db_session.add(settings)
        db_session.commit()

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user, word)
        _make_direction(
            db_session, uw,
            state=CardState.NEW.value,
            next_review=now - timedelta(minutes=1),
        )

        with patch('app.daily_plan.assembler.get_daily_plan_mix_word_ids', return_value=[word.id]):
            result = _has_guided_recall_content(user.id)
        assert result is False
