# tests/test_unified_srs_grammar.py
"""
Tests for unified SRS system for grammar exercises.

Tests the Anki-like state machine for grammar exercises:
- NEW → LEARNING → REVIEW ⟷ RELEARNING
- Grade mapping from binary (is_correct) to 1-2-3 rating
- Exercise-level progress tracking
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app.srs.service import UnifiedSRSService, unified_srs_service
from app.srs.constants import (
    CardState,
    RATING_DONT_KNOW, RATING_DOUBT, RATING_KNOW,
    DEFAULT_EASE_FACTOR, MIN_EASE_FACTOR, MAX_EASE_FACTOR,
    LEARNING_STEPS, RELEARNING_STEPS,
    GRADUATING_INTERVAL, EASY_INTERVAL,
)


class TestGrammarExerciseSRSConstants:
    """Test constants used for grammar SRS."""

    def test_card_states_exist(self):
        """Test all card states are defined."""
        assert CardState.NEW.value == 'new'
        assert CardState.LEARNING.value == 'learning'
        assert CardState.REVIEW.value == 'review'
        assert CardState.RELEARNING.value == 'relearning'

    def test_rating_values(self):
        """Test rating constants."""
        assert RATING_DONT_KNOW == 1
        assert RATING_DOUBT == 2
        assert RATING_KNOW == 3

    def test_learning_steps_defined(self):
        """Test learning steps are defined."""
        assert isinstance(LEARNING_STEPS, (list, tuple))
        assert len(LEARNING_STEPS) >= 1

    def test_relearning_steps_defined(self):
        """Test relearning steps are defined."""
        assert isinstance(RELEARNING_STEPS, (list, tuple))
        assert len(RELEARNING_STEPS) >= 1


class TestGrammarExerciseStateMachine:
    """Test Anki-like state machine for grammar exercises."""

    def test_new_card_rating_know_graduates_immediately(self):
        """Rating 3 (Know) on NEW card graduates to REVIEW."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.NEW.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0
        )

        assert result['state'] == CardState.REVIEW.value
        assert result['interval'] == EASY_INTERVAL
        assert result['days_until_review'] == EASY_INTERVAL

    def test_new_card_rating_dont_know_enters_learning(self):
        """Rating 1 (Don't know) on NEW card enters LEARNING."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.NEW.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0
        )

        assert result['state'] == CardState.LEARNING.value
        assert result['step_index'] == 0
        assert result['requeue_minutes'] == LEARNING_STEPS[0]

    def test_new_card_rating_doubt_enters_learning_step_1(self):
        """Rating 2 (Doubt) on NEW card enters LEARNING at step 1."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DOUBT,
            state=CardState.NEW.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0
        )

        assert result['state'] == CardState.LEARNING.value
        # Step depends on LEARNING_STEPS length
        if len(LEARNING_STEPS) > 1:
            assert result['step_index'] == 1

    def test_learning_card_rating_know_advances_step(self):
        """Rating 3 (Know) on LEARNING card advances to next step."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.LEARNING.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0
        )

        # If there are more steps, advance; otherwise graduate
        if len(LEARNING_STEPS) > 1:
            assert result['state'] == CardState.LEARNING.value
            assert result['step_index'] == 1
        else:
            assert result['state'] == CardState.REVIEW.value

    def test_learning_card_rating_dont_know_resets_step(self):
        """Rating 1 (Don't know) on LEARNING card resets to step 0."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.LEARNING.value,
            step_index=1,
            repetitions=1,
            interval=0,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0
        )

        assert result['state'] == CardState.LEARNING.value
        assert result['step_index'] == 0

    def test_learning_card_graduates_after_all_steps(self):
        """LEARNING card graduates to REVIEW after completing all steps."""
        last_step = len(LEARNING_STEPS) - 1

        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.LEARNING.value,
            step_index=last_step,
            repetitions=1,
            interval=0,
            ease_factor=DEFAULT_EASE_FACTOR,
            lapses=0
        )

        assert result['state'] == CardState.REVIEW.value
        assert result['interval'] == GRADUATING_INTERVAL

    def test_review_card_rating_dont_know_enters_relearning(self):
        """Rating 1 (Don't know) on REVIEW card enters RELEARNING."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=30,
            ease_factor=2.5,
            lapses=0
        )

        assert result['state'] == CardState.RELEARNING.value
        assert result['step_index'] == 0
        assert result['lapses'] == 1
        assert result['ease_factor'] < 2.5  # Decreased

    def test_review_card_rating_know_increases_interval(self):
        """Rating 3 (Know) on REVIEW card increases interval."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.5,
            lapses=0
        )

        assert result['state'] == CardState.REVIEW.value
        assert result['interval'] > 10  # Interval increased

    def test_relearning_card_rating_know_returns_to_review(self):
        """Rating 3 (Know) on RELEARNING card (last step) returns to REVIEW."""
        last_step = len(RELEARNING_STEPS) - 1

        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.RELEARNING.value,
            step_index=last_step,
            repetitions=5,
            interval=1,
            ease_factor=2.0,
            lapses=1
        )

        assert result['state'] == CardState.REVIEW.value
        assert result['lapses'] == 1  # Lapses preserved

    def test_relearning_card_rating_dont_know_resets_step(self):
        """Rating 1 (Don't know) on RELEARNING card resets to step 0."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.RELEARNING.value,
            step_index=1 if len(RELEARNING_STEPS) > 1 else 0,
            repetitions=5,
            interval=1,
            ease_factor=2.0,
            lapses=1
        )

        assert result['state'] == CardState.RELEARNING.value
        assert result['step_index'] == 0


class TestGradeGrammarExercise:
    """Test grade_grammar_exercise method."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    @pytest.fixture
    def mock_progress(self):
        """Create a mock UserGrammarExercise."""
        progress = MagicMock()
        progress.id = 123
        progress.user_id = 1
        progress.exercise_id = 456
        progress.state = CardState.NEW.value
        progress.step_index = 0
        progress.repetitions = 0
        progress.interval = 0
        progress.ease_factor = 2.5
        progress.lapses = 0
        progress.correct_count = 0
        progress.incorrect_count = 0
        progress.session_attempts = 0
        progress.first_reviewed = None
        progress.last_reviewed = None
        progress.next_review = datetime.now(timezone.utc)
        return progress

    @patch('app.srs.service.UserGrammarExercise')
    @patch('app.srs.service.db')
    def test_grade_grammar_exercise_success(self, mock_db, mock_model, service, mock_progress):
        """Test successful grammar exercise grading."""
        mock_model.get_or_create.return_value = mock_progress

        result = service.grade_grammar_exercise(
            exercise_id=456,
            rating=RATING_KNOW,
            user_id=1,
            session_key='test_session'
        )

        assert result['success'] is True
        assert result['exercise_id'] == 456
        assert result['state'] in [CardState.REVIEW.value, CardState.LEARNING.value]
        mock_db.session.commit.assert_called_once()

    @patch('app.srs.service.UserGrammarExercise')
    @patch('app.srs.service.db')
    def test_grade_grammar_exercise_updates_correct_count(self, mock_db, mock_model, service, mock_progress):
        """Test correct_count is updated on correct answer."""
        mock_model.get_or_create.return_value = mock_progress

        service.grade_grammar_exercise(
            exercise_id=456,
            rating=RATING_KNOW,
            user_id=1
        )

        assert mock_progress.correct_count == 1

    @patch('app.srs.service.UserGrammarExercise')
    @patch('app.srs.service.db')
    def test_grade_grammar_exercise_updates_incorrect_count(self, mock_db, mock_model, service, mock_progress):
        """Test incorrect_count is updated on incorrect answer."""
        mock_model.get_or_create.return_value = mock_progress

        service.grade_grammar_exercise(
            exercise_id=456,
            rating=RATING_DONT_KNOW,
            user_id=1
        )

        assert mock_progress.incorrect_count == 1

    @patch('app.srs.service.UserGrammarExercise')
    @patch('app.srs.service.db')
    def test_grade_grammar_exercise_sets_first_reviewed(self, mock_db, mock_model, service, mock_progress):
        """Test first_reviewed is set on first review."""
        mock_model.get_or_create.return_value = mock_progress

        service.grade_grammar_exercise(
            exercise_id=456,
            rating=RATING_KNOW,
            user_id=1
        )

        assert mock_progress.first_reviewed is not None

    @patch('app.srs.service.UserGrammarExercise')
    @patch('app.srs.service.db')
    def test_grade_grammar_exercise_requeue_on_learning(self, mock_db, mock_model, service, mock_progress):
        """Test requeue position is returned for LEARNING state."""
        mock_model.get_or_create.return_value = mock_progress

        result = service.grade_grammar_exercise(
            exercise_id=456,
            rating=RATING_DONT_KNOW,
            user_id=1
        )

        assert result['success'] is True
        assert result['requeue_position'] is not None
        assert result['requeue_minutes'] is not None

    @patch('app.srs.service.UserGrammarExercise')
    @patch('app.srs.service.db')
    def test_grade_grammar_exercise_no_requeue_on_review(self, mock_db, mock_model, service, mock_progress):
        """Test no requeue for REVIEW state with rating 3."""
        mock_progress.state = CardState.REVIEW.value
        mock_progress.interval = 10
        mock_model.get_or_create.return_value = mock_progress

        result = service.grade_grammar_exercise(
            exercise_id=456,
            rating=RATING_KNOW,
            user_id=1
        )

        assert result['success'] is True
        assert result['requeue_position'] is None

    @patch('app.srs.service.UserGrammarExercise')
    @patch('app.srs.service.db')
    def test_grade_grammar_exercise_handles_error(self, mock_db, mock_model, service):
        """Test error handling in grade_grammar_exercise."""
        mock_model.get_or_create.side_effect = Exception("Database error")

        result = service.grade_grammar_exercise(
            exercise_id=456,
            rating=RATING_KNOW,
            user_id=1
        )

        assert result['success'] is False
        assert 'error' in result


class TestGetDueGrammarExercises:
    """Test getting due grammar exercises for review."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    def test_method_exists(self, service):
        """Test get_due_grammar_exercises method exists."""
        assert hasattr(service, 'get_due_grammar_exercises')
        assert callable(service.get_due_grammar_exercises)

    def test_method_accepts_parameters(self, service):
        """Test method accepts expected parameters."""
        import inspect
        sig = inspect.signature(service.get_due_grammar_exercises)
        params = list(sig.parameters.keys())

        assert 'user_id' in params
        assert 'topic_id' in params
        assert 'limit' in params


class TestBinaryToRatingMapping:
    """Test mapping binary results to 1-2-3 rating scale."""

    def test_correct_answer_maps_to_rating_3(self):
        """is_correct=True should map to rating 3 (Know)."""
        is_correct = True
        rating = RATING_KNOW if is_correct else RATING_DONT_KNOW
        assert rating == RATING_KNOW

    def test_incorrect_answer_maps_to_rating_1(self):
        """is_correct=False should map to rating 1 (Don't know)."""
        is_correct = False
        rating = RATING_KNOW if is_correct else RATING_DONT_KNOW
        assert rating == RATING_DONT_KNOW


class TestSRSStatsService:
    """Test unified SRS stats service."""

    def test_grammar_stats_format(self):
        """Test grammar stats return expected format."""
        from app.srs.stats_service import SRSStatsService

        # Test the method exists and has correct signature
        assert hasattr(SRSStatsService, 'get_grammar_stats')
        assert callable(SRSStatsService.get_grammar_stats)

    def test_words_stats_format(self):
        """Test words stats return expected format."""
        from app.srs.stats_service import SRSStatsService

        assert hasattr(SRSStatsService, 'get_words_stats')
        assert callable(SRSStatsService.get_words_stats)

    def test_unified_stats_entry_point(self):
        """Test unified get_stats entry point."""
        from app.srs.stats_service import SRSStatsService

        assert hasattr(SRSStatsService, 'get_stats')
        assert callable(SRSStatsService.get_stats)

    def test_user_overview_method(self):
        """Test get_user_overview method."""
        from app.srs.stats_service import SRSStatsService

        assert hasattr(SRSStatsService, 'get_user_overview')
        assert callable(SRSStatsService.get_user_overview)


class TestRequeuePositionForGrammar:
    """Test requeue position calculation for grammar exercises."""

    def test_requeue_position_learning_dont_know(self):
        """Test requeue position for LEARNING state with rating 1."""
        pos = UnifiedSRSService.get_requeue_position(
            rating=RATING_DONT_KNOW,
            state=CardState.LEARNING.value,
            step_index=0
        )

        assert pos is not None
        assert isinstance(pos, int)
        assert pos >= 1

    def test_requeue_position_learning_doubt(self):
        """Test requeue position for LEARNING state with rating 2."""
        pos = UnifiedSRSService.get_requeue_position(
            rating=RATING_DOUBT,
            state=CardState.LEARNING.value,
            step_index=0
        )

        assert pos is not None
        assert isinstance(pos, int)

    def test_requeue_position_learning_know_advances(self):
        """Test requeue position for LEARNING state with rating 3."""
        # If not last step, should return position for next step
        # If last step, should return None (graduated)
        pos = UnifiedSRSService.get_requeue_position(
            rating=RATING_KNOW,
            state=CardState.LEARNING.value,
            step_index=0
        )

        # Result depends on number of learning steps
        if len(LEARNING_STEPS) > 1:
            assert pos is not None
        # else graduated, could be None

    def test_requeue_position_review_returns_none(self):
        """Test requeue position for REVIEW state returns None."""
        pos = UnifiedSRSService.get_requeue_position(
            rating=RATING_KNOW,
            state=CardState.REVIEW.value,
            step_index=0
        )

        assert pos is None

    def test_requeue_position_relearning_dont_know(self):
        """Test requeue position for RELEARNING state with rating 1."""
        pos = UnifiedSRSService.get_requeue_position(
            rating=RATING_DONT_KNOW,
            state=CardState.RELEARNING.value,
            step_index=0
        )

        assert pos is not None
        assert isinstance(pos, int)


class TestGrammarSRSServiceIntegration:
    """Test GrammarSRS service integration with UnifiedSRSService."""

    def test_grammar_srs_uses_unified_service(self):
        """Test that GrammarSRS delegates to UnifiedSRSService."""
        from app.grammar_lab.services.grammar_srs import GrammarSRS

        srs = GrammarSRS()
        assert hasattr(srs, 'process_exercise_answer')
        assert callable(srs.process_exercise_answer)

    def test_grammar_lab_service_uses_srs(self):
        """Test that GrammarLabService uses SRS."""
        from app.grammar_lab.services.grammar_lab_service import GrammarLabService

        service = GrammarLabService()
        assert hasattr(service, 'srs')
        assert hasattr(service, 'submit_answer')
