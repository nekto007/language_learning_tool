"""Tests for ease_factor increment and first_reviewed correctness in legacy UserCardDirection state machine (Tasks 3-4)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.srs.constants import (
    CardState,
    DEFAULT_EASE_FACTOR,
    EF_INCREASE_EASY,
    LEARNING_STEPS,
    MAX_EASE_FACTOR,
    RATING_DOUBT,
    RATING_DONT_KNOW,
    RATING_KNOW,
)
from app.study.models import UserCardDirection, UserWord
from app.utils.time_utils import day_to_naive_utc
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_card(db_session, user_id: int, state: str, *, step_index: int = 0,
               ease_factor: float = DEFAULT_EASE_FACTOR) -> UserCardDirection:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'ef_{suffix}',
        russian_word=f'ef_ru_{suffix}',
        level='A1',
    )
    db_session.add(word)
    db_session.flush()

    uw = UserWord(user_id=user_id, word_id=word.id)
    uw.status = 'new'
    db_session.add(uw)
    db_session.flush()

    card = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
    card.state = state
    card.step_index = step_index
    card.ease_factor = ease_factor
    card.interval = 0
    card.repetitions = 0
    card.lapses = 0
    card.next_review = _now_naive()
    db_session.add(card)
    db_session.flush()
    return card


class TestNewCardEaseFactorIncrement:
    """NEW + KNOW must raise ease_factor by EF_INCREASE_EASY (capped at MAX)."""

    def test_new_know_increments_ease_factor(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, CardState.NEW.value,
                          ease_factor=DEFAULT_EASE_FACTOR)
        initial_ef = card.ease_factor

        card.update_after_review(quality=RATING_KNOW)

        assert card.state == CardState.REVIEW.value
        expected = min(MAX_EASE_FACTOR, initial_ef + EF_INCREASE_EASY)
        assert abs(card.ease_factor - expected) < 1e-9

    def test_new_know_ease_factor_capped_at_max(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, CardState.NEW.value,
                          ease_factor=MAX_EASE_FACTOR)

        card.update_after_review(quality=RATING_KNOW)

        assert card.state == CardState.REVIEW.value
        assert card.ease_factor <= MAX_EASE_FACTOR

    def test_new_dont_know_does_not_change_ease_factor(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, CardState.NEW.value,
                          ease_factor=DEFAULT_EASE_FACTOR)
        initial_ef = card.ease_factor

        card.update_after_review(quality=RATING_DONT_KNOW)

        assert card.state == CardState.LEARNING.value
        assert abs(card.ease_factor - initial_ef) < 1e-9

    def test_new_doubt_does_not_change_ease_factor(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, CardState.NEW.value,
                          ease_factor=DEFAULT_EASE_FACTOR)
        initial_ef = card.ease_factor

        card.update_after_review(quality=RATING_DOUBT)

        assert card.state == CardState.LEARNING.value
        assert abs(card.ease_factor - initial_ef) < 1e-9


class TestLearningCardGraduationEaseFactorIncrement:
    """LEARNING card graduating (last step → REVIEW) must raise ease_factor."""

    def _advance_to_last_step(self, db_session, test_user):
        """Advance a card to the last LEARNING step."""
        card = _make_card(db_session, test_user.id, CardState.LEARNING.value,
                          step_index=len(LEARNING_STEPS) - 1,
                          ease_factor=DEFAULT_EASE_FACTOR)
        return card

    def test_learning_graduation_increments_ease_factor(self, db_session, test_user):
        card = self._advance_to_last_step(db_session, test_user)
        initial_ef = card.ease_factor

        card.update_after_review(quality=RATING_KNOW)

        assert card.state == CardState.REVIEW.value
        expected = min(MAX_EASE_FACTOR, initial_ef + EF_INCREASE_EASY)
        assert abs(card.ease_factor - expected) < 1e-9

    def test_learning_non_final_step_does_not_increment_ease(self, db_session, test_user):
        # Step 0, not the last step: no increment
        card = _make_card(db_session, test_user.id, CardState.LEARNING.value,
                          step_index=0, ease_factor=DEFAULT_EASE_FACTOR)
        initial_ef = card.ease_factor

        card.update_after_review(quality=RATING_KNOW)

        # Card still in LEARNING (not graduated), ease_factor unchanged
        assert card.state == CardState.LEARNING.value
        assert abs(card.ease_factor - initial_ef) < 1e-9

    def test_learning_graduation_capped_at_max(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, CardState.LEARNING.value,
                          step_index=len(LEARNING_STEPS) - 1,
                          ease_factor=MAX_EASE_FACTOR)

        card.update_after_review(quality=RATING_KNOW)

        assert card.state == CardState.REVIEW.value
        assert card.ease_factor <= MAX_EASE_FACTOR

    def test_learning_dont_know_does_not_increment_ease(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, CardState.LEARNING.value,
                          step_index=len(LEARNING_STEPS) - 1,
                          ease_factor=DEFAULT_EASE_FACTOR)
        initial_ef = card.ease_factor

        card.update_after_review(quality=RATING_DONT_KNOW)

        # Reset to step 0, not graduated
        assert card.state == CardState.LEARNING.value
        assert abs(card.ease_factor - initial_ef) < 1e-9

    def test_learning_doubt_at_last_step_does_not_increment_ease(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, CardState.LEARNING.value,
                          step_index=len(LEARNING_STEPS) - 1,
                          ease_factor=DEFAULT_EASE_FACTOR)
        initial_ef = card.ease_factor

        card.update_after_review(quality=RATING_DOUBT)

        # Hard: repeat the step, no graduation
        assert card.state == CardState.LEARNING.value
        assert abs(card.ease_factor - initial_ef) < 1e-9


class TestFirstReviewedLegacyPath:
    """Regression tests for first_reviewed in legacy update_after_review (Task 4).

    The legacy path sets first_reviewed on the first review only — subsequent
    reviews must not overwrite the timestamp.
    """

    def test_new_card_gets_first_reviewed_on_first_grade(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, CardState.NEW.value)
        assert card.first_reviewed is None

        card.update_after_review(quality=RATING_KNOW)

        # first_reviewed must be populated after the first grade
        assert card.first_reviewed is not None
        # Strip tzinfo if the legacy path left it tz-aware (column is naive-UTC)
        fr = card.first_reviewed.replace(tzinfo=None) if card.first_reviewed.tzinfo else card.first_reviewed
        # Day-anchored (user-local midnight), shared with grade_card — not a
        # raw instant. Matches the local-day boundary in app/srs/counting.py.
        assert fr == day_to_naive_utc(test_user.id, db_session, days_ahead=0)

    def test_first_reviewed_not_overwritten_on_second_grade(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, CardState.NEW.value)

        # First review
        card.update_after_review(quality=RATING_DONT_KNOW)  # NEW → LEARNING
        first_ts = card.first_reviewed
        assert first_ts is not None

        # Second review — must not overwrite first_ts
        card.update_after_review(quality=RATING_KNOW)
        second_ts = card.first_reviewed

        # Normalise tzinfo for comparison
        def naive(ts):
            return ts.replace(tzinfo=None) if ts and ts.tzinfo else ts

        assert naive(second_ts) == naive(first_ts)

    def test_first_reviewed_not_overwritten_on_review_state_grade(self, db_session, test_user):
        """Card already in REVIEW state (has first_reviewed) must not overwrite it."""
        existing_ts = datetime(2025, 1, 1, 12, 0, 0)  # naive-UTC sentinel
        card = _make_card(db_session, test_user.id, CardState.REVIEW.value)
        card.first_reviewed = existing_ts
        card.interval = 1
        card.next_review = _now_naive()
        db_session.flush()

        card.update_after_review(quality=RATING_KNOW)

        def naive(ts):
            return ts.replace(tzinfo=None) if ts and ts.tzinfo else ts

        assert naive(card.first_reviewed) == existing_ts

    def test_new_card_first_reviewed_with_dont_know(self, db_session, test_user):
        """Even a DONT_KNOW rating on a NEW card must set first_reviewed."""
        card = _make_card(db_session, test_user.id, CardState.NEW.value)
        assert card.first_reviewed is None

        card.update_after_review(quality=RATING_DONT_KNOW)

        assert card.first_reviewed is not None
