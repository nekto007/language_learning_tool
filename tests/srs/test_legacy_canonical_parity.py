"""
Task 12: Verify that legacy update_after_review and canonical calculate_sm2_update
produce identical SM-2 fields for all key grading scenarios.

After the refactoring, update_after_review delegates its SM-2 math to
calculate_sm2_update, so both paths must agree on:
  state, step_index, interval, ease_factor, lapses, repetitions
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import pytest

from app.srs.constants import (
    CardState,
    DEFAULT_EASE_FACTOR,
    EF_DECREASE_HARD,
    EF_DECREASE_LAPSE,
    EF_INCREASE_EASY,
    GRADUATING_INTERVAL,
    LEARNING_STEPS,
    LEECH_SUSPEND_DAYS,
    LEECH_THRESHOLD,
    LAPSE_MINIMUM_INTERVAL,
    MAX_EASE_FACTOR,
    MIN_EASE_FACTOR,
    RATING_DONT_KNOW,
    RATING_DOUBT,
    RATING_KNOW,
    RELEARNING_STEPS,
)
from app.srs.service import UnifiedSRSService
from app.study.models import UserCardDirection, UserWord
from app.words.models import CollectionWords


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_card(
    db_session,
    user_id: int,
    *,
    state: str,
    step_index: int = 0,
    ease_factor: float = DEFAULT_EASE_FACTOR,
    interval: int = 0,
    repetitions: int = 0,
    lapses: int = 0,
) -> UserCardDirection:
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'parity_{suffix}',
        russian_word=f'parity_ru_{suffix}',
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
    card.interval = interval
    card.repetitions = repetitions
    card.lapses = lapses
    card.next_review = _now_naive()
    card.first_reviewed = None
    card.last_reviewed = None
    card.correct_count = 0
    card.incorrect_count = 0
    card.session_attempts = 0
    db_session.add(card)
    db_session.flush()
    return card


def _sm2_fields(card: UserCardDirection) -> Dict[str, Any]:
    """Extract the SM-2 fields we compare between paths."""
    return {
        'state': card.state,
        'step_index': card.step_index,
        'interval': card.interval,
        'ease_factor': card.ease_factor,
        'lapses': card.lapses,
        'repetitions': card.repetitions,
    }


# ---------------------------------------------------------------------------
# Parametrised scenario table
# Each entry: (scenario_id, initial_state, step_index, interval, ease_factor,
#              lapses, repetitions, rating)
# ---------------------------------------------------------------------------

_SCENARIOS = [
    # NEW state
    ('new_know',        CardState.NEW.value,        0, 0, DEFAULT_EASE_FACTOR, 0, 0, RATING_KNOW),
    ('new_dont_know',   CardState.NEW.value,        0, 0, DEFAULT_EASE_FACTOR, 0, 0, RATING_DONT_KNOW),
    ('new_doubt',       CardState.NEW.value,        0, 0, DEFAULT_EASE_FACTOR, 0, 0, RATING_DOUBT),

    # LEARNING state — non-final step (step 0 of 3)
    ('learning_s0_know',      CardState.LEARNING.value, 0, 0, DEFAULT_EASE_FACTOR, 0, 1, RATING_KNOW),
    ('learning_s0_dont_know', CardState.LEARNING.value, 0, 0, DEFAULT_EASE_FACTOR, 0, 1, RATING_DONT_KNOW),
    ('learning_s0_doubt',     CardState.LEARNING.value, 0, 0, DEFAULT_EASE_FACTOR, 0, 1, RATING_DOUBT),

    # LEARNING state — last step → graduation
    ('learning_last_know',      CardState.LEARNING.value, len(LEARNING_STEPS) - 1, 0, DEFAULT_EASE_FACTOR, 0, 2, RATING_KNOW),
    ('learning_last_dont_know', CardState.LEARNING.value, len(LEARNING_STEPS) - 1, 0, DEFAULT_EASE_FACTOR, 0, 2, RATING_DONT_KNOW),

    # REVIEW state
    ('review_know',      CardState.REVIEW.value, 0, 10, DEFAULT_EASE_FACTOR, 0, 5, RATING_KNOW),
    ('review_doubt',     CardState.REVIEW.value, 0, 10, DEFAULT_EASE_FACTOR, 0, 5, RATING_DOUBT),
    ('review_dont_know', CardState.REVIEW.value, 0, 10, DEFAULT_EASE_FACTOR, 0, 5, RATING_DONT_KNOW),

    # REVIEW at min ease_factor
    ('review_min_ef_know',  CardState.REVIEW.value, 0, 5, MIN_EASE_FACTOR, 2, 5, RATING_KNOW),
    ('review_min_ef_doubt', CardState.REVIEW.value, 0, 5, MIN_EASE_FACTOR, 2, 5, RATING_DOUBT),

    # REVIEW leech threshold — lapse triggers bury signal
    ('review_leech_threshold', CardState.REVIEW.value, 0, 10, DEFAULT_EASE_FACTOR,
     LEECH_THRESHOLD - 1, 5, RATING_DONT_KNOW),
    ('review_above_leech', CardState.REVIEW.value, 0, 10, MIN_EASE_FACTOR,
     LEECH_THRESHOLD + 2, 5, RATING_DONT_KNOW),

    # RELEARNING state — step 0
    ('relearning_s0_know',      CardState.RELEARNING.value, 0, LAPSE_MINIMUM_INTERVAL, DEFAULT_EASE_FACTOR, 1, 3, RATING_KNOW),
    ('relearning_s0_dont_know', CardState.RELEARNING.value, 0, LAPSE_MINIMUM_INTERVAL, DEFAULT_EASE_FACTOR, 1, 3, RATING_DONT_KNOW),
    ('relearning_s0_doubt',     CardState.RELEARNING.value, 0, LAPSE_MINIMUM_INTERVAL, DEFAULT_EASE_FACTOR, 1, 3, RATING_DOUBT),

    # RELEARNING state — last step → graduation back to REVIEW
    ('relearning_last_know', CardState.RELEARNING.value, len(RELEARNING_STEPS) - 1,
     LAPSE_MINIMUM_INTERVAL, DEFAULT_EASE_FACTOR, 1, 4, RATING_KNOW),
]


class TestLegacyCanonicalParity:
    """
    Verify SM-2 field parity between update_after_review (legacy wrapper) and
    calculate_sm2_update (canonical engine) for every key grading scenario.

    After Task 12 refactoring, update_after_review delegates to
    calculate_sm2_update, so the fields must be byte-identical.
    """

    @pytest.mark.parametrize(
        'scenario_id,initial_state,step_index,interval,ease_factor,lapses,repetitions,rating',
        [(s[0], *s[1:]) for s in _SCENARIOS],
        ids=[s[0] for s in _SCENARIOS],
    )
    def test_sm2_fields_identical(
        self,
        db_session,
        test_user,
        scenario_id,
        initial_state,
        step_index,
        interval,
        ease_factor,
        lapses,
        repetitions,
        rating,
    ):
        # Canonical engine (pure function)
        canonical = UnifiedSRSService.calculate_sm2_update(
            rating=rating,
            state=initial_state,
            step_index=step_index,
            repetitions=repetitions,
            interval=interval,
            ease_factor=ease_factor,
            lapses=lapses,
        )

        # Legacy wrapper (operates on a real DB card)
        card = _make_card(
            db_session,
            test_user.id,
            state=initial_state,
            step_index=step_index,
            ease_factor=ease_factor,
            interval=interval,
            repetitions=repetitions,
            lapses=lapses,
        )
        card.update_after_review(quality=rating)

        legacy = _sm2_fields(card)

        assert legacy['state'] == canonical['state'], (
            f"[{scenario_id}] state: legacy={legacy['state']} canonical={canonical['state']}"
        )
        assert legacy['step_index'] == canonical['step_index'], (
            f"[{scenario_id}] step_index: legacy={legacy['step_index']} canonical={canonical['step_index']}"
        )
        assert legacy['interval'] == canonical['interval'], (
            f"[{scenario_id}] interval: legacy={legacy['interval']} canonical={canonical['interval']}"
        )
        assert abs(legacy['ease_factor'] - canonical['ease_factor']) < 1e-9, (
            f"[{scenario_id}] ease_factor: legacy={legacy['ease_factor']} canonical={canonical['ease_factor']}"
        )
        assert legacy['lapses'] == canonical['lapses'], (
            f"[{scenario_id}] lapses: legacy={legacy['lapses']} canonical={canonical['lapses']}"
        )
        assert legacy['repetitions'] == canonical['repetitions'], (
            f"[{scenario_id}] repetitions: legacy={legacy['repetitions']} canonical={canonical['repetitions']}"
        )


class TestLegacyWrapperExtraFields:
    """
    Verify that update_after_review correctly updates the extra fields not
    managed by calculate_sm2_update: correct/incorrect counts, session_attempts,
    first_reviewed, last_reviewed, and next_review.
    """

    def test_first_reviewed_set_on_new_card(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, state=CardState.NEW.value)
        assert card.first_reviewed is None

        before = _now_naive()
        card.update_after_review(quality=RATING_KNOW)
        after = _now_naive()

        assert card.first_reviewed is not None
        assert card.first_reviewed.tzinfo is None, 'first_reviewed must be naive-UTC'
        assert before <= card.first_reviewed <= after

    def test_first_reviewed_not_overwritten(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, state=CardState.NEW.value)
        card.update_after_review(quality=RATING_DONT_KNOW)
        original_ts = card.first_reviewed

        card.update_after_review(quality=RATING_KNOW)

        assert card.first_reviewed == original_ts

    def test_last_reviewed_naive_utc(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, state=CardState.NEW.value)
        card.update_after_review(quality=RATING_KNOW)

        assert card.last_reviewed is not None
        assert card.last_reviewed.tzinfo is None, 'last_reviewed must be naive-UTC'

    def test_correct_count_incremented_on_know(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, state=CardState.NEW.value)
        card.update_after_review(quality=RATING_KNOW)
        assert card.correct_count == 1
        assert card.incorrect_count == 0

    def test_incorrect_count_incremented_on_dont_know(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, state=CardState.NEW.value)
        card.update_after_review(quality=RATING_DONT_KNOW)
        assert card.incorrect_count == 1
        assert card.correct_count == 0

    def test_session_attempts_incremented(self, db_session, test_user):
        card = _make_card(db_session, test_user.id, state=CardState.NEW.value)
        card.update_after_review(quality=RATING_KNOW)
        assert card.session_attempts == 1

        card.update_after_review(quality=RATING_DOUBT)
        assert card.session_attempts == 2

    def test_leech_bury_applied_at_threshold(self, db_session, test_user):
        card = _make_card(
            db_session, test_user.id,
            state=CardState.REVIEW.value,
            interval=10,
            lapses=LEECH_THRESHOLD - 1,
        )
        before = _now_naive()
        card.update_after_review(quality=RATING_DONT_KNOW)

        assert card.lapses == LEECH_THRESHOLD
        assert card.buried_until is not None
        # buried_until should be approximately LEECH_SUSPEND_DAYS days from now
        expected_bury = before + timedelta(days=LEECH_SUSPEND_DAYS)
        assert card.buried_until >= before
        diff = abs((card.buried_until - expected_bury).total_seconds())
        assert diff < 5, 'buried_until should be ~LEECH_SUSPEND_DAYS from now'

    def test_next_review_set_days_for_review_state(self, db_session, test_user):
        card = _make_card(
            db_session, test_user.id,
            state=CardState.REVIEW.value,
            interval=10,
            ease_factor=DEFAULT_EASE_FACTOR,
        )
        before = _now_naive()
        card.update_after_review(quality=RATING_KNOW)

        assert card.next_review is not None
        assert card.next_review.tzinfo is None, 'next_review must be naive-UTC'
        # next_review should be at least 1 day in the future
        assert card.next_review > before + timedelta(hours=12)

    def test_next_review_set_minutes_for_learning_state(self, db_session, test_user):
        card = _make_card(
            db_session, test_user.id,
            state=CardState.NEW.value,
        )
        before = _now_naive()
        card.update_after_review(quality=RATING_DONT_KNOW)

        # Card is now LEARNING; next_review should be minutes away, not days
        assert card.state == CardState.LEARNING.value
        assert card.next_review is not None
        # Should be less than 1 day away (learning steps are minutes)
        assert card.next_review < before + timedelta(days=1)

    def test_legacy_mapping_zero_becomes_dont_know(self, db_session, test_user):
        """Legacy callers may pass quality=0; must be treated as RATING_DONT_KNOW."""
        card = _make_card(db_session, test_user.id, state=CardState.NEW.value)
        card.update_after_review(quality=0)

        canonical = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.NEW.value,
            step_index=0, repetitions=0, interval=0,
            ease_factor=DEFAULT_EASE_FACTOR, lapses=0,
        )
        assert card.state == canonical['state']

    def test_legacy_mapping_five_becomes_know(self, db_session, test_user):
        """Legacy callers may pass quality=5; must be treated as RATING_KNOW."""
        card = _make_card(db_session, test_user.id, state=CardState.NEW.value)
        card.update_after_review(quality=5)

        canonical = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.NEW.value,
            step_index=0, repetitions=0, interval=0,
            ease_factor=DEFAULT_EASE_FACTOR, lapses=0,
        )
        assert card.state == canonical['state']
        assert abs(card.ease_factor - canonical['ease_factor']) < 1e-9
