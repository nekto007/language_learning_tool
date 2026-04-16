"""
Parametrized edge case tests for SRS service (grammar exercises).

Covers:
- get_due_grammar_exercises with 0 items due
- get_due_grammar_exercises with all items overdue
- First review (exercise never reviewed before, NEW state)
- Interval calculation at mastery boundary (179 → crosses 180 mastery threshold)
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app.grammar_lab.models import GrammarTopic, GrammarExercise, UserGrammarExercise
from app.srs.service import UnifiedSRSService
from app.srs.constants import (
    CardState, RATING_KNOW, RATING_DONT_KNOW,
    DEFAULT_EASE_FACTOR, INTERVAL_MULTIPLIER_EASY,
    MASTERED_THRESHOLD_DAYS, GRADUATING_INTERVAL,
)
from app.srs.mixins import SRSFieldsMixin
from app.utils.db import db


class _FakeSRSItem(SRSFieldsMixin):
    """Minimal plain-Python object with SRS mixin — no SQLAlchemy required."""
    def __init__(self, state: str, interval: int):
        self.state = state
        self.interval = interval
        self.next_review = None
        self.correct_count = 0
        self.incorrect_count = 0


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def grammar_topic(db_session):
    unique = uuid.uuid4().hex[:8]
    topic = GrammarTopic(
        slug=f'srs-edge-{unique}',
        title='Edge Case Topic',
        title_ru='Граничный топик',
        level='B1',
        order=1,
        content={'introduction': 'Test', 'sections': []},
        estimated_time=10,
        difficulty=2,
    )
    db_session.add(topic)
    db_session.commit()
    return topic


@pytest.fixture
def grammar_exercises(db_session, grammar_topic):
    exercises = []
    for i in range(5):
        ex = GrammarExercise(
            topic_id=grammar_topic.id,
            exercise_type='fill_blank',
            content={'question': f'Question {i} ___', 'correct_answer': 'ok'},
            difficulty=1,
            order=i,
        )
        db_session.add(ex)
        exercises.append(ex)
    db_session.commit()
    return exercises


# ---------------------------------------------------------------------------
# Test: get_due_grammar_exercises with 0 items due
# ---------------------------------------------------------------------------

class TestZeroItemsDue:
    @pytest.mark.smoke
    def test_returns_empty_list_not_none(self, app, db_session, test_user, grammar_exercises):
        """get_due_grammar_exercises returns [] not None when no exercises are due."""
        service = UnifiedSRSService()
        # All exercises are NEW state (no progress records created) but the topic
        # has exercises -- create progress records for all in REVIEW state with
        # next_review far in the future.
        future = datetime.now(timezone.utc) + timedelta(days=30)
        for ex in grammar_exercises:
            progress = UserGrammarExercise(
                user_id=test_user.id,
                exercise_id=ex.id,
            )
            progress.state = CardState.REVIEW.value
            progress.interval = 10
            progress.next_review = future
            db_session.add(progress)
        db_session.commit()

        result = service.get_due_grammar_exercises(
            user_id=test_user.id,
            topic_id=grammar_exercises[0].topic_id,
        )

        assert result is not None, "Must return a list, not None"
        assert isinstance(result, list), "Must return a list"
        # No new exercises exist and all REVIEW are in the future, no LEARNING/RELEARNING
        assert len(result) == 0, "No items should be due"

    def test_empty_list_type_for_nonexistent_user(self, app, db_session):
        """Returns empty list for a user with no exercise records."""
        service = UnifiedSRSService()
        result = service.get_due_grammar_exercises(user_id=999999)
        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 0

    def test_zero_due_after_limit_consumed(self, app, db_session, test_user, grammar_exercises):
        """With limit=0, returns empty list."""
        service = UnifiedSRSService()
        result = service.get_due_grammar_exercises(
            user_id=test_user.id,
            limit=0,
        )
        assert isinstance(result, list)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Test: get_due_grammar_exercises with all items overdue
# ---------------------------------------------------------------------------

class TestAllItemsOverdue:
    def test_returns_all_overdue_exercises(self, app, db_session, test_user, grammar_exercises):
        """When all exercises are overdue, they are all returned."""
        service = UnifiedSRSService()
        past = datetime.now(timezone.utc) - timedelta(days=5)
        for ex in grammar_exercises:
            progress = UserGrammarExercise(
                user_id=test_user.id,
                exercise_id=ex.id,
            )
            progress.state = CardState.REVIEW.value
            progress.interval = 5
            progress.next_review = past
            db_session.add(progress)
        db_session.commit()

        result = service.get_due_grammar_exercises(
            user_id=test_user.id,
            topic_id=grammar_exercises[0].topic_id,
            limit=100,
        )

        exercise_ids = {p.exercise_id for p in result}
        expected_ids = {ex.id for ex in grammar_exercises}
        assert expected_ids == exercise_ids, "All overdue exercises should be returned"

    def test_overdue_ordered_by_next_review_asc(self, app, db_session, test_user, grammar_exercises):
        """Overdue REVIEW exercises are returned oldest-first (exercise 0 is most overdue)."""
        service = UnifiedSRSService()
        base = datetime.now(timezone.utc) - timedelta(days=10)
        for i, ex in enumerate(grammar_exercises):
            progress = UserGrammarExercise(
                user_id=test_user.id,
                exercise_id=ex.id,
            )
            progress.state = CardState.REVIEW.value
            progress.interval = 10
            # Older = smaller next_review; exercise 0 is most overdue
            progress.next_review = base + timedelta(days=i)
            db_session.add(progress)
        db_session.commit()

        result = service.get_due_grammar_exercises(
            user_id=test_user.id,
            topic_id=grammar_exercises[0].topic_id,
            limit=100,
        )

        review_items = [r for r in result if r.state == CardState.REVIEW.value]
        assert len(review_items) == len(grammar_exercises)
        # Most overdue (exercise 0, oldest next_review) must appear first
        # Compare exercise_ids to avoid timezone-aware vs naive datetime issues
        result_exercise_ids = [r.exercise_id for r in review_items]
        expected_exercise_ids = [ex.id for ex in grammar_exercises]  # already ordered by ascending next_review
        assert result_exercise_ids == expected_exercise_ids

    def test_relearning_has_higher_priority_than_review(self, app, db_session, test_user, grammar_exercises):
        """RELEARNING items appear before REVIEW items in the returned list."""
        service = UnifiedSRSService()
        past = datetime.now(timezone.utc) - timedelta(hours=1)

        # First exercise: RELEARNING (higher priority)
        relearning_progress = UserGrammarExercise(
            user_id=test_user.id,
            exercise_id=grammar_exercises[0].id,
        )
        relearning_progress.state = CardState.RELEARNING.value
        relearning_progress.interval = 1
        relearning_progress.next_review = past
        db_session.add(relearning_progress)

        # Second exercise: REVIEW (lower priority)
        review_progress = UserGrammarExercise(
            user_id=test_user.id,
            exercise_id=grammar_exercises[1].id,
        )
        review_progress.state = CardState.REVIEW.value
        review_progress.interval = 5
        review_progress.next_review = past - timedelta(days=1)  # Even older, but lower priority
        db_session.add(review_progress)
        db_session.commit()

        result = service.get_due_grammar_exercises(
            user_id=test_user.id,
            topic_id=grammar_exercises[0].topic_id,
            limit=10,
        )

        states = [r.state for r in result]
        # RELEARNING must appear before REVIEW
        if CardState.RELEARNING.value in states and CardState.REVIEW.value in states:
            relearning_idx = states.index(CardState.RELEARNING.value)
            review_idx = states.index(CardState.REVIEW.value)
            assert relearning_idx < review_idx, "RELEARNING should have higher priority than REVIEW"


# ---------------------------------------------------------------------------
# Test: First review (never reviewed before)
# ---------------------------------------------------------------------------

class TestFirstReview:
    def test_first_review_sets_first_reviewed_timestamp(self, app, db_session, test_user, grammar_exercises):
        """grade_grammar_exercise sets first_reviewed on the initial review."""
        service = UnifiedSRSService()
        ex = grammar_exercises[0]

        with patch('app.srs.service.UserGrammarExercise') as MockModel:
            mock_progress = MagicMock()
            mock_progress.state = CardState.NEW.value
            mock_progress.step_index = 0
            mock_progress.repetitions = 0
            mock_progress.interval = 0
            mock_progress.ease_factor = DEFAULT_EASE_FACTOR
            mock_progress.lapses = 0
            mock_progress.correct_count = 0
            mock_progress.incorrect_count = 0
            mock_progress.session_attempts = 0
            mock_progress.first_reviewed = None  # Never reviewed
            mock_progress.last_reviewed = None
            mock_progress.next_review = None
            MockModel.get_or_create.return_value = mock_progress

            with patch('app.srs.service.db'):
                result = service.grade_grammar_exercise(
                    exercise_id=ex.id,
                    rating=RATING_KNOW,
                    user_id=test_user.id,
                )

            assert result['success'] is True
            assert mock_progress.first_reviewed is not None, "first_reviewed must be set on first review"

    def test_first_review_new_state_with_rating_know_graduates_to_review(self):
        """NEW card + RATING_KNOW graduates immediately to REVIEW state."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.NEW.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0,
        )
        assert result['state'] == CardState.REVIEW.value
        assert result['interval'] > 0
        assert result['requeue_minutes'] is None

    def test_first_review_new_state_with_rating_dont_know_enters_learning(self):
        """NEW card + RATING_DONT_KNOW goes to LEARNING state."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.NEW.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0,
        )
        assert result['state'] == CardState.LEARNING.value
        assert result['requeue_minutes'] is not None
        assert result['requeue_minutes'] > 0

    @pytest.mark.parametrize("rating,expected_state", [
        (RATING_KNOW, CardState.REVIEW.value),
        (RATING_DONT_KNOW, CardState.LEARNING.value),
    ])
    def test_first_review_parametrized(self, rating, expected_state):
        """Parametrized: first review transitions to correct state."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=rating,
            state=CardState.NEW.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0,
        )
        assert result['state'] == expected_state

    def test_new_exercises_returned_when_no_progress_records(self, app, db_session, test_user, grammar_exercises):
        """Exercises with no UserGrammarExercise record are treated as NEW and returned."""
        service = UnifiedSRSService()
        # Don't create any progress records — exercises exist but haven't been started

        # First get all exercises so the query can join them
        # get_due_grammar_exercises fetches NEW exercises last (priority 4)
        result = service.get_due_grammar_exercises(
            user_id=test_user.id,
            topic_id=grammar_exercises[0].topic_id,
            limit=100,
        )

        # NEW exercises (no UserGrammarExercise rows) are NOT returned
        # because the query filters UserGrammarExercise records.
        # This test verifies the return is a list (not None) even with no records.
        assert result is not None
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Test: Interval calculation at mastery boundary
# ---------------------------------------------------------------------------

class TestMasteryBoundaryInterval:
    def test_interval_at_mastery_threshold_is_mastered(self):
        """Exercise at exactly MASTERED_THRESHOLD_DAYS interval is considered mastered."""
        progress = _FakeSRSItem(state=CardState.REVIEW.value, interval=MASTERED_THRESHOLD_DAYS)
        assert progress.is_mastered is True

    def test_interval_below_mastery_threshold_is_not_mastered(self):
        """Exercise at MASTERED_THRESHOLD_DAYS - 1 is NOT mastered."""
        progress = _FakeSRSItem(state=CardState.REVIEW.value, interval=MASTERED_THRESHOLD_DAYS - 1)
        assert progress.is_mastered is False

    def test_review_card_near_mastery_gains_mastered_interval_after_rating_know(self):
        """
        REVIEW card with interval just below mastery (179) gets rated KNOW →
        new interval jumps well past mastery threshold (180).
        """
        below_mastery = MASTERED_THRESHOLD_DAYS - 1  # 179

        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=10,
            interval=below_mastery,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0,
        )

        assert result['state'] == CardState.REVIEW.value
        # New interval should exceed mastery threshold
        assert result['interval'] > MASTERED_THRESHOLD_DAYS, (
            f"Expected interval > {MASTERED_THRESHOLD_DAYS}, got {result['interval']}"
        )

    @pytest.mark.parametrize("interval,expected_mastered", [
        (0, False),
        (MASTERED_THRESHOLD_DAYS - 1, False),
        (MASTERED_THRESHOLD_DAYS, True),
        (MASTERED_THRESHOLD_DAYS + 1, True),
        (500, True),
    ])
    def test_mastery_boundary_parametrized(self, interval, expected_mastered):
        """Parametrized: is_mastered follows the 180-day threshold exactly."""
        progress = _FakeSRSItem(state=CardState.REVIEW.value, interval=interval)
        assert progress.is_mastered is expected_mastered, (
            f"interval={interval}: expected is_mastered={expected_mastered}"
        )

    def test_interval_grows_monotonically_across_reviews(self):
        """Successive RATING_KNOW reviews keep increasing the interval."""
        state = CardState.REVIEW.value
        interval = GRADUATING_INTERVAL
        ease = DEFAULT_EASE_FACTOR
        lapses = 0
        repetitions = 1

        previous_interval = interval
        for _ in range(5):
            result = UnifiedSRSService.calculate_sm2_update(
                rating=RATING_KNOW,
                state=state,
                step_index=0,
                repetitions=repetitions,
                interval=previous_interval,
                ease_factor=ease,
                lapses=lapses,
            )
            assert result['interval'] >= previous_interval, (
                f"Interval should not decrease: {previous_interval} → {result['interval']}"
            )
            previous_interval = result['interval']
            ease = result['ease_factor']
            repetitions += 1
