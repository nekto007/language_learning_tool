"""Task 6: Tests for repetitions==0 proxy removal in book/curriculum SRS.

Verify that card state (CardState enum) — not repetitions count — determines
whether a card is "new".  A post-lapse card has repetitions=0 but state=REVIEW
(or RELEARNING), so it must NOT be treated as a fresh new card.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

import pytest

from app.auth.models import User
from app.curriculum.services.book_srs_integration import BookSRSIntegration
from app.srs.constants import CardState, DEFAULT_EASE_FACTOR
from app.study.models import UserCardDirection, UserWord
from app.words.models import CollectionWords


@pytest.fixture()
def user(db_session):
    s = uuid.uuid4().hex[:10]
    u = User(username=f"bksrs_{s}", email=f"bksrs_{s}@example.com", active=True)
    u.set_password("pass")
    db_session.add(u)
    db_session.commit()
    return u


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _naive_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_word(db_session) -> CollectionWords:
    s = uuid.uuid4().hex[:8]
    word = CollectionWords(english_word=f"bk_{s}", russian_word=f"бк_{s}", level="A1")
    db_session.add(word)
    db_session.commit()
    return word


def _make_user_word(db_session, user_id: int, word: CollectionWords, status: str = "new") -> UserWord:
    uw = UserWord(user_id=user_id, word_id=word.id)
    uw.status = status
    db_session.add(uw)
    db_session.commit()
    return uw


def _make_card(
    db_session,
    user_word: UserWord,
    *,
    state: str = CardState.NEW.value,
    repetitions: int = 0,
    interval: int = 0,
    next_review: datetime | None = None,
    direction: str = "eng-rus",
) -> UserCardDirection:
    card = UserCardDirection(
        user_word_id=user_word.id,
        direction=direction,
        source="book_reading",
    )
    card.state = state
    card.repetitions = repetitions
    card.interval = interval
    card.ease_factor = DEFAULT_EASE_FACTOR
    card.next_review = next_review if next_review is not None else _naive_now()
    db_session.add(card)
    db_session.commit()
    return card


def _card_item(card: UserCardDirection, context: str | None = None) -> Dict[str, Any]:
    """Wrap a card in the dict format that _filter_due_cards expects."""
    return {"card": card, "context": context, "unit_type": None, "note": None}


# ---------------------------------------------------------------------------
# _filter_due_cards — state-based new detection
# ---------------------------------------------------------------------------

class TestFilterDueCards:
    """BookSRSIntegration._filter_due_cards uses CardState, not repetitions."""

    def test_new_state_card_is_included(self, db_session, user):
        """Card with state=NEW is always due (brand new card)."""
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        card = _make_card(
            db_session, uw,
            state=CardState.NEW.value,
            repetitions=0,
            next_review=_naive_now() + timedelta(days=1),  # future
        )

        srs = BookSRSIntegration()
        result = srs._filter_due_cards([_card_item(card)])
        assert len(result) == 1

    def test_review_card_repetitions_zero_not_treated_as_new(self, db_session, user):
        """Post-lapse card: state=REVIEW, repetitions=0 — not 'new', future due → excluded."""
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        card = _make_card(
            db_session, uw,
            state=CardState.REVIEW.value,
            repetitions=0,
            next_review=_naive_now() + timedelta(days=2),
        )

        srs = BookSRSIntegration()
        result = srs._filter_due_cards([_card_item(card)])
        assert len(result) == 0, (
            "A REVIEW card with repetitions=0 (post-lapse) and future due date "
            "must NOT be returned as due"
        )

    def test_review_card_overdue_is_included(self, db_session, user):
        """REVIEW card that is past its next_review time should be returned."""
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        card = _make_card(
            db_session, uw,
            state=CardState.REVIEW.value,
            repetitions=5,
            next_review=_naive_now() - timedelta(hours=1),
        )

        srs = BookSRSIntegration()
        result = srs._filter_due_cards([_card_item(card)])
        assert len(result) == 1

    def test_relearning_card_repetitions_zero_not_treated_as_new(self, db_session, user):
        """RELEARNING card with repetitions=0 and future due → excluded."""
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        card = _make_card(
            db_session, uw,
            state=CardState.RELEARNING.value,
            repetitions=0,
            next_review=_naive_now() + timedelta(hours=12),
        )

        srs = BookSRSIntegration()
        result = srs._filter_due_cards([_card_item(card)])
        assert len(result) == 0

    def test_direction_filter_respected(self, db_session, user):
        """direction_filter kwarg excludes non-matching directions."""
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        card_er = _make_card(db_session, uw, state=CardState.NEW.value, direction="eng-rus")
        card_re = _make_card(db_session, uw, state=CardState.NEW.value, direction="rus-eng")

        srs = BookSRSIntegration()
        items = [_card_item(card_er), _card_item(card_re)]
        result = srs._filter_due_cards(items, direction_filter="eng-rus")
        assert len(result) == 1
        assert result[0]["card"].direction == "eng-rus"


# ---------------------------------------------------------------------------
# get_due_cards_count — state-based counting + status filter + naive UTC
# ---------------------------------------------------------------------------

class TestGetDueCardsCount:
    """BookSRSIntegration.get_due_cards_count uses state, not repetitions."""

    def test_new_state_card_counted(self, db_session, user):
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        _make_card(db_session, uw, state=CardState.NEW.value, repetitions=0)

        srs = BookSRSIntegration()
        count = srs.get_due_cards_count(user.id)
        assert count >= 1

    def test_review_card_repetitions_zero_not_counted_as_new(self, db_session, user):
        """Post-lapse REVIEW card with future due date must NOT inflate due count."""
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        _make_card(
            db_session, uw,
            state=CardState.REVIEW.value,
            repetitions=0,
            next_review=_naive_now() + timedelta(days=7),
        )

        srs = BookSRSIntegration()
        count = srs.get_due_cards_count(user.id)
        assert count == 0, (
            "REVIEW card with repetitions=0 (post-lapse) that isn't yet due "
            "must not be counted"
        )

    def test_overdue_review_card_counted(self, db_session, user):
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        _make_card(
            db_session, uw,
            state=CardState.REVIEW.value,
            repetitions=5,
            next_review=_naive_now() - timedelta(days=1),
        )

        srs = BookSRSIntegration()
        count = srs.get_due_cards_count(user.id)
        assert count >= 1

    def test_mastered_user_word_excluded(self, db_session, user):
        """Cards whose UserWord.status='mastered' are excluded."""
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word, status="mastered")
        _make_card(db_session, uw, state=CardState.NEW.value)

        srs = BookSRSIntegration()
        count = srs.get_due_cards_count(user.id)
        assert count == 0

    def test_future_due_review_card_not_counted(self, db_session, user):
        """Non-new card due in the future is not counted."""
        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        _make_card(
            db_session, uw,
            state=CardState.REVIEW.value,
            repetitions=3,
            next_review=_naive_now() + timedelta(days=5),
        )

        srs = BookSRSIntegration()
        count = srs.get_due_cards_count(user.id)
        assert count == 0


# ---------------------------------------------------------------------------
# Task 9: caller-commits contract — helpers flush, do NOT commit
# ---------------------------------------------------------------------------

class TestCallerCommitsContract:
    """Verify that SRS helpers flush but do not commit; rollback discards new cards."""

    def test_get_or_create_card_direction_flushes_not_commits(self, db_session, user):
        """
        _get_or_create_card_direction creates a card via flush.
        Rolling back the transaction (simulating exception in caller) discards it.
        """
        from app.utils.db import db

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)

        srs = BookSRSIntegration()

        # Before: no card directions for this user_word
        count_before = UserCardDirection.query.filter_by(user_word_id=uw.id).count()
        assert count_before == 0

        # Call the helper — it flushes so the new card has an id
        card = srs._get_or_create_card_direction(uw, 'eng-rus')
        assert card.id is not None, "flush should assign a PK"

        # Within the same session the card is visible
        count_flushed = UserCardDirection.query.filter_by(user_word_id=uw.id).count()
        assert count_flushed == 1

        # Simulate caller exception — roll back without committing
        db.session.rollback()

        # After rollback the card must not be persisted
        count_after = UserCardDirection.query.filter_by(user_word_id=uw.id).count()
        assert count_after == 0, (
            "_get_or_create_card_direction must flush only; "
            "rollback should discard the new card"
        )

    def test_process_card_grade_flushes_not_commits(self, db_session, user):
        """
        process_card_grade updates a card via flush.
        Rolling back discards the update.
        """
        from app.utils.db import db

        word = _make_word(db_session)
        uw = _make_user_word(db_session, user.id, word)
        card = _make_card(
            db_session, uw,
            state=CardState.REVIEW.value,
            repetitions=3,
            next_review=_naive_now() - timedelta(hours=1),
        )
        original_repetitions = card.repetitions

        srs = BookSRSIntegration()
        result = srs.process_card_grade(user.id, card.id, grade=4, session_key='test')
        assert result['success'] is True

        # Update is visible in current session (after flush)
        db_session.refresh(card)
        assert card.repetitions != original_repetitions or card.interval != 0

        # Roll back — the update must be discarded
        db.session.rollback()

        # Re-fetch and verify the original state is restored
        restored = UserCardDirection.query.get(card.id)
        assert restored.repetitions == original_repetitions
