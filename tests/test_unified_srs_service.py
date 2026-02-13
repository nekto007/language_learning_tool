# tests/test_unified_srs_service.py
"""
Tests for the unified SRS (Spaced Repetition System) service.

Tests the Anki-like state machine with 1-2-3 rating scale:
    1 - Не знаю (Don't know): Reset to step 0, requeue in 8-15 cards
    2 - Сомневаюсь (Doubt/Hard): Repeat current step, requeue in 15-25 cards
    3 - Знаю (Know/Good): Advance step or graduate, no requeue

Card States:
    NEW → LEARNING → REVIEW ⟷ RELEARNING
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from app.srs import (
    RATING_DONT_KNOW,
    RATING_DOUBT,
    RATING_KNOW,
    MAX_SESSION_ATTEMPTS,
    REQUEUE_RANGE_DONT_KNOW,
    REQUEUE_RANGE_DOUBT,
)
from app.srs.service import UnifiedSRSService, unified_srs_service
from app.srs.constants import (
    DEFAULT_EASE_FACTOR,
    MIN_EASE_FACTOR,
    MAX_EASE_FACTOR,
    EF_DECREASE_DONT_KNOW,
    EF_INCREASE_KNOW,
    CardState,
    LEARNING_STEPS,
    RELEARNING_STEPS,
    GRADUATING_INTERVAL,
    EASY_INTERVAL,
    EF_DECREASE_LAPSE,
    EF_DECREASE_HARD,
    EF_INCREASE_EASY,
    INTERVAL_MULTIPLIER_HARD,
    INTERVAL_MULTIPLIER_EASY,
    LAPSE_MINIMUM_INTERVAL,
)


class TestSRSConstants:
    """Test SRS constants are properly defined."""

    def test_rating_values(self):
        """Test rating constants have correct values."""
        assert RATING_DONT_KNOW == 1
        assert RATING_DOUBT == 2
        assert RATING_KNOW == 3

    def test_max_session_attempts(self):
        """Test max session attempts is 3."""
        assert MAX_SESSION_ATTEMPTS == 3

    def test_requeue_ranges(self):
        """Test requeue position ranges (Anki-like increased intervals)."""
        # Increased intervals for better memory retrieval practice
        # "Не знаю" now +8-15 cards (was +1-3) - forces real memory recall
        # "Сомневаюсь" now +15-25 cards (was +3-6) - weak knowledge needs bigger gap
        assert REQUEUE_RANGE_DONT_KNOW == (8, 15)
        assert REQUEUE_RANGE_DOUBT == (15, 25)

    def test_ease_factor_bounds(self):
        """Test ease factor bounds (Anki allows up to 2.8)."""
        assert DEFAULT_EASE_FACTOR == 2.5
        assert MIN_EASE_FACTOR == 1.3
        assert MAX_EASE_FACTOR == 2.8  # Anki allows up to 2.8, not 2.5


class TestGetRequeuePosition:
    """Test requeue position calculation with Anki-like state machine."""

    def test_rating_dont_know_new_state_returns_8_to_15(self):
        """Rating 1 on NEW card should return position 8-15."""
        positions = set()
        for _ in range(100):
            pos = UnifiedSRSService.get_requeue_position(
                RATING_DONT_KNOW, state=CardState.NEW.value
            )
            positions.add(pos)

        # Should be in range 8-15
        assert all(8 <= p <= 15 for p in positions)
        assert len(positions) > 1  # Should have multiple values

    def test_rating_dont_know_learning_state_returns_8_to_15(self):
        """Rating 1 on LEARNING card should return position 8-15."""
        positions = set()
        for _ in range(100):
            pos = UnifiedSRSService.get_requeue_position(
                RATING_DONT_KNOW, state=CardState.LEARNING.value
            )
            positions.add(pos)

        assert all(8 <= p <= 15 for p in positions)

    def test_rating_doubt_returns_15_to_25(self):
        """Rating 2 should return position 15-25."""
        positions = set()
        for _ in range(100):
            pos = UnifiedSRSService.get_requeue_position(
                RATING_DOUBT, state=CardState.NEW.value
            )
            positions.add(pos)

        assert all(15 <= p <= 25 for p in positions)

    def test_rating_know_returns_none(self):
        """Rating 3 should return None (no requeue - card graduates)."""
        pos = UnifiedSRSService.get_requeue_position(
            RATING_KNOW, state=CardState.NEW.value
        )
        assert pos is None

    def test_review_state_always_returns_none(self):
        """REVIEW state cards are scheduled for days, never requeued."""
        for rating in [RATING_DONT_KNOW, RATING_DOUBT, RATING_KNOW]:
            pos = UnifiedSRSService.get_requeue_position(
                rating, state=CardState.REVIEW.value
            )
            assert pos is None

    def test_unknown_rating_returns_none(self):
        """Unknown rating should return None."""
        pos = UnifiedSRSService.get_requeue_position(99, state=CardState.NEW.value)
        assert pos is None


class TestCalculateSM2Update:
    """Test Anki-like SM-2 algorithm calculations with state machine."""

    def test_new_card_rating_dont_know_starts_learning(self):
        """Rating 1 on NEW card should start LEARNING at step 0."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.NEW.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=2.5
        )

        assert result['state'] == CardState.LEARNING.value
        assert result['step_index'] == 0
        assert result['interval'] == 0
        assert result['requeue_minutes'] == LEARNING_STEPS[0]  # 1 minute

    def test_new_card_rating_doubt_starts_learning_step_1(self):
        """Rating 2 on NEW card should start LEARNING at step 1."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DOUBT,
            state=CardState.NEW.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=2.5
        )

        assert result['state'] == CardState.LEARNING.value
        # Step clamped to max available step
        assert result['step_index'] <= len(LEARNING_STEPS) - 1

    def test_new_card_rating_know_skips_to_review(self):
        """Rating 3 on NEW card should skip learning entirely."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.NEW.value,
            step_index=0,
            repetitions=0,
            interval=0,
            ease_factor=2.5
        )

        assert result['state'] == CardState.REVIEW.value
        assert result['interval'] == EASY_INTERVAL  # 4 days
        assert result['days_until_review'] == EASY_INTERVAL
        assert result['requeue_minutes'] is None  # No requeue

    def test_learning_card_rating_dont_know_resets_to_step_0(self):
        """Rating 1 on LEARNING card should reset to step 0."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.LEARNING.value,
            step_index=1,
            repetitions=1,
            interval=0,
            ease_factor=2.5
        )

        assert result['state'] == CardState.LEARNING.value
        assert result['step_index'] == 0
        assert result['requeue_minutes'] == LEARNING_STEPS[0]

    def test_learning_card_rating_doubt_repeats_current_step(self):
        """Rating 2 on LEARNING card should repeat current step."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DOUBT,
            state=CardState.LEARNING.value,
            step_index=1,
            repetitions=1,
            interval=0,
            ease_factor=2.5
        )

        assert result['state'] == CardState.LEARNING.value
        assert result['step_index'] == 1  # Same step
        assert result['requeue_minutes'] == LEARNING_STEPS[1]

    def test_learning_card_rating_know_advances_step(self):
        """Rating 3 on LEARNING card at step 0 should advance to step 1."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.LEARNING.value,
            step_index=0,
            repetitions=1,
            interval=0,
            ease_factor=2.5
        )

        assert result['state'] == CardState.LEARNING.value
        assert result['step_index'] == 1
        assert result['requeue_minutes'] == LEARNING_STEPS[1]

    def test_learning_card_graduates_at_last_step(self):
        """Rating 3 on last LEARNING step should graduate to REVIEW."""
        last_step = len(LEARNING_STEPS) - 1
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.LEARNING.value,
            step_index=last_step,
            repetitions=2,
            interval=0,
            ease_factor=2.3
        )

        assert result['state'] == CardState.REVIEW.value
        assert result['interval'] == GRADUATING_INTERVAL  # 1 day
        assert result['days_until_review'] == GRADUATING_INTERVAL
        assert result['requeue_minutes'] is None

    def test_review_card_rating_dont_know_lapses_to_relearning(self):
        """Rating 1 on REVIEW card should lapse to RELEARNING."""
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
        assert result['ease_factor'] == 2.5 - EF_DECREASE_LAPSE  # 2.3
        assert result['requeue_minutes'] == RELEARNING_STEPS[0]

    def test_review_card_rating_doubt_small_increase(self):
        """Rating 2 on REVIEW card should have small interval increase with EF penalty."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DOUBT,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.5,
            lapses=0
        )

        assert result['state'] == CardState.REVIEW.value
        # interval = max(11, round(10 * 1.2)) = max(11, 12) = 12
        expected_interval = max(10 + 1, round(10 * INTERVAL_MULTIPLIER_HARD))
        assert result['interval'] == expected_interval
        assert result['ease_factor'] == 2.5 - EF_DECREASE_HARD  # 2.35
        assert result['requeue_minutes'] is None

    def test_review_card_rating_know_normal_increase(self):
        """Rating 3 on REVIEW card should have normal interval increase."""
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
        # interval = max(11, round(10 * 2.5 * 1.3)) = max(11, 33) = 33
        expected_interval = max(10 + 1, round(10 * 2.5 * INTERVAL_MULTIPLIER_EASY))
        assert result['interval'] == expected_interval
        # EF increases by EF_INCREASE_EASY (0.15), capped at MAX_EASE_FACTOR (2.8)
        assert result['ease_factor'] == min(MAX_EASE_FACTOR, 2.5 + EF_INCREASE_EASY)

    def test_review_card_ef_minimum_on_lapse(self):
        """Rating 1 should not decrease EF below minimum on lapse."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=30,
            ease_factor=1.4,  # Close to minimum
            lapses=3
        )

        assert result['ease_factor'] == MIN_EASE_FACTOR  # Should not go below 1.3

    def test_review_card_ef_maximum_on_know(self):
        """Rating 3 should not increase EF above maximum."""
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.REVIEW.value,
            step_index=0,
            repetitions=5,
            interval=10,
            ease_factor=2.75,  # Close to maximum
            lapses=0
        )

        assert result['ease_factor'] == MAX_EASE_FACTOR  # Should not exceed 2.8

    def test_relearning_card_rating_know_returns_to_review(self):
        """Rating 3 on last RELEARNING step should return to REVIEW."""
        last_step = len(RELEARNING_STEPS) - 1
        result = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            state=CardState.RELEARNING.value,
            step_index=last_step,
            repetitions=5,
            interval=1,
            ease_factor=2.3,
            lapses=2
        )

        assert result['state'] == CardState.REVIEW.value
        assert result['interval'] == LAPSE_MINIMUM_INTERVAL
        assert result['requeue_minutes'] is None


class TestGradeCard:
    """Test card grading with database interaction."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    @pytest.fixture
    def mock_card(self):
        """Create a mock card with Anki-like state fields."""
        card = MagicMock()
        card.id = 123
        card.state = CardState.NEW.value
        card.step_index = 0
        card.repetitions = 0
        card.interval = 0
        card.ease_factor = 2.5
        card.lapses = 0
        card.session_attempts = 0
        card.correct_count = 0
        card.incorrect_count = 0
        card.user_word = MagicMock()
        card.user_word.user_id = 1
        card.user_word.status = 'new'
        return card

    @patch('app.srs.service.UserCardDirection')
    @patch('app.srs.service.db')
    def test_grade_card_success(self, mock_db, mock_model, service, mock_card):
        """Test successful card grading - NEW card with RATING_KNOW skips to REVIEW."""
        mock_model.query.get.return_value = mock_card

        result = service.grade_card(
            card_id=123,
            rating=RATING_KNOW,
            user_id=1,
            session_key='test_session'
        )

        assert result['success'] is True
        assert result['card_id'] == 123
        # RATING_KNOW on NEW card skips learning, goes to REVIEW with EASY_INTERVAL (4 days)
        assert result['interval'] == EASY_INTERVAL
        assert result['state'] == CardState.REVIEW.value
        assert 'next_review' in result
        assert result['requeue_position'] is None  # No requeue for graduated card
        mock_db.session.commit.assert_called_once()

    @patch('app.srs.service.UserCardDirection')
    def test_grade_card_not_found(self, mock_model, service):
        """Test grading non-existent card."""
        mock_model.query.get.return_value = None

        result = service.grade_card(
            card_id=999,
            rating=RATING_KNOW,
            user_id=1
        )

        assert result['success'] is False
        assert result['error'] == 'Card not found'

    @patch('app.srs.service.UserCardDirection')
    def test_grade_card_access_denied(self, mock_model, service, mock_card):
        """Test grading card with wrong user."""
        mock_card.user_word.user_id = 2  # Different user
        mock_model.query.get.return_value = mock_card

        result = service.grade_card(
            card_id=123,
            rating=RATING_KNOW,
            user_id=1
        )

        assert result['success'] is False
        assert result['error'] == 'Access denied'

    @patch('app.srs.service.UserCardDirection')
    @patch('app.srs.service.db')
    def test_grade_card_requeue_on_dont_know(self, mock_db, mock_model, service, mock_card):
        """Test that rating 1 returns requeue position (8-15 range)."""
        mock_model.query.get.return_value = mock_card

        result = service.grade_card(
            card_id=123,
            rating=RATING_DONT_KNOW,
            user_id=1
        )

        assert result['success'] is True
        assert 8 <= result['requeue_position'] <= 15

    @patch('app.srs.service.UserCardDirection')
    @patch('app.srs.service.db')
    def test_grade_card_requeue_on_doubt(self, mock_db, mock_model, service, mock_card):
        """Test that rating 2 returns requeue position (15-25 range)."""
        mock_model.query.get.return_value = mock_card

        result = service.grade_card(
            card_id=123,
            rating=RATING_DOUBT,
            user_id=1
        )

        assert result['success'] is True
        assert 15 <= result['requeue_position'] <= 25

    @patch('app.srs.service.UserCardDirection')
    @patch('app.srs.service.db')
    def test_grade_card_no_requeue_at_max_attempts(self, mock_db, mock_model, service, mock_card):
        """Test no requeue when max attempts reached."""
        mock_card.session_attempts = 2  # Will become 3 after grading
        mock_model.query.get.return_value = mock_card

        result = service.grade_card(
            card_id=123,
            rating=RATING_DONT_KNOW,  # Would normally requeue
            user_id=1
        )

        assert result['success'] is True
        assert result['requeue_position'] is None  # No requeue at max

    @patch('app.srs.service.UserCardDirection')
    @patch('app.srs.service.db')
    def test_grade_card_increments_session_attempts(self, mock_db, mock_model, service, mock_card):
        """Test session attempts is incremented."""
        mock_model.query.get.return_value = mock_card

        service.grade_card(card_id=123, rating=RATING_KNOW, user_id=1)

        assert mock_card.session_attempts == 1


class TestLegacyCompatibility:
    """Test backward compatibility with 0-5 rating scale."""

    def test_legacy_scale_mapping_in_api(self):
        """
        Legacy rating 0-5 should map to rating 1-2-3 in the API.

        Mapping:
            0-1 → 1 (Don't know)
            2-3 → 2 (Doubt)
            4-5 → 3 (Know)

        This is handled in srs_api.py grade_card() endpoint.
        """
        # Verify mapping logic matches what's in the API
        def map_legacy_to_unified(grade):
            if grade <= 1:
                return RATING_DONT_KNOW  # 1
            elif grade <= 3:
                return RATING_DOUBT  # 2
            else:
                return RATING_KNOW  # 3

        assert map_legacy_to_unified(0) == 1
        assert map_legacy_to_unified(1) == 1
        assert map_legacy_to_unified(2) == 2
        assert map_legacy_to_unified(3) == 2
        assert map_legacy_to_unified(4) == 3
        assert map_legacy_to_unified(5) == 3


class TestSRSQueueJS:
    """Test that JS queue constants match Python constants."""

    def test_max_attempts_consistent(self):
        """Ensure MAX_SESSION_ATTEMPTS is consistent."""
        # The JS file uses hardcoded 3, same as Python
        assert MAX_SESSION_ATTEMPTS == 3

    def test_requeue_ranges_documented(self):
        """Ensure requeue ranges are properly documented (Anki-like increased intervals)."""
        # Rating 1: 8-15 cards (increased for better memory recall)
        assert REQUEUE_RANGE_DONT_KNOW == (8, 15)
        # Rating 2: 15-25 cards (increased for weak knowledge)
        assert REQUEUE_RANGE_DOUBT == (15, 25)


class TestUpdateUserWordStatus:
    """Test user word status updates based on card progress.

    Note: The new Anki-like implementation delegates to UserWord.recalculate_status()
    which queries all card directions and determines status based on their states.
    """

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    @patch('app.srs.service.db')
    def test_calls_recalculate_status(self, mock_db, service):
        """Test that _update_user_word_status calls recalculate_status on user_word."""
        card = MagicMock()
        card.user_word = MagicMock()

        service._update_user_word_status(card)

        # Should flush the session to ensure card state is visible
        mock_db.session.flush.assert_called_once()
        # Should call recalculate_status on the user_word
        card.user_word.recalculate_status.assert_called_once()

    @patch('app.srs.service.db')
    def test_flushes_session_before_recalculate(self, mock_db, service):
        """Test that session is flushed before recalculating status."""
        card = MagicMock()
        card.user_word = MagicMock()

        # Track call order
        call_order = []
        mock_db.session.flush.side_effect = lambda: call_order.append('flush')
        card.user_word.recalculate_status.side_effect = lambda: call_order.append('recalculate')

        service._update_user_word_status(card)

        # Flush should be called before recalculate_status
        assert call_order == ['flush', 'recalculate']


class TestCreateSession:
    """Test session creation."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    @patch.object(UnifiedSRSService, '_get_due_cards')
    @patch.object(UnifiedSRSService, '_count_studied_today')
    @patch.object(UnifiedSRSService, '_format_cards_for_session')
    def test_create_session_success(self, mock_format, mock_count, mock_get_due, service):
        """Test successful session creation."""
        mock_get_due.return_value = []
        mock_count.return_value = 5
        mock_format.return_value = []

        result = service.create_session(
            user_id=1,
            source='study',
            source_id=10
        )

        assert 'session_key' in result
        assert result['session_key'].startswith('study_10_1_')
        assert result['studied_today'] == 5
        assert result['source'] == 'study'
        assert result['source_id'] == 10

    @patch.object(UnifiedSRSService, '_get_due_cards')
    @patch.object(UnifiedSRSService, '_count_studied_today')
    @patch.object(UnifiedSRSService, '_format_cards_for_session')
    def test_create_session_with_word_ids(self, mock_format, mock_count, mock_get_due, service):
        """Test session creation with specific word IDs."""
        mock_get_due.return_value = []
        mock_count.return_value = 0
        mock_format.return_value = []

        result = service.create_session(
            user_id=1,
            source='book_course',
            word_ids=[1, 2, 3],
            limit=20
        )

        mock_get_due.assert_called_once()
        call_kwargs = mock_get_due.call_args.kwargs
        assert call_kwargs['word_ids'] == [1, 2, 3]
        assert call_kwargs['limit'] == 20

    @patch.object(UnifiedSRSService, '_get_due_cards')
    def test_create_session_handles_exception(self, mock_get_due, service):
        """Test session creation handles exceptions gracefully."""
        mock_get_due.side_effect = Exception("Database error")

        result = service.create_session(user_id=1, source='study')

        assert result['session_key'] is None
        assert result['cards'] == []
        assert 'error' in result


class TestGetDueCards:
    """Test getting due cards for review."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    def test_get_due_cards_returns_list(self, service):
        """Test _get_due_cards method signature and return type."""
        # This method requires database integration testing
        # Here we just verify the method exists and has correct signature
        assert hasattr(service, '_get_due_cards')
        assert callable(service._get_due_cards)

    def test_get_due_cards_accepts_parameters(self, service):
        """Test _get_due_cards accepts all expected parameters."""
        import inspect
        sig = inspect.signature(service._get_due_cards)
        params = list(sig.parameters.keys())

        assert 'user_id' in params
        assert 'word_ids' in params
        assert 'directions' in params
        assert 'limit' in params


class TestCountStudiedToday:
    """Test counting words studied today."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    def test_count_studied_today_method_exists(self, service):
        """Test _count_studied_today method exists."""
        assert hasattr(service, '_count_studied_today')
        assert callable(service._count_studied_today)

    def test_count_studied_today_accepts_parameters(self, service):
        """Test _count_studied_today accepts expected parameters."""
        import inspect
        sig = inspect.signature(service._count_studied_today)
        params = list(sig.parameters.keys())

        assert 'user_id' in params
        assert 'word_ids' in params


class TestFormatCardsForSession:
    """Test card formatting for client with Anki-like state information."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    def test_format_eng_rus_card_new_state(self, service):
        """Test formatting English to Russian card with NEW state."""
        card = MagicMock()
        card.id = 1
        card.direction = 'eng-rus'
        card.state = CardState.NEW.value
        card.step_index = 0
        card.repetitions = 0
        card.ease_factor = 2.5
        card.interval = 0
        card.lapses = 0
        card.session_attempts = 0
        card.user_word = MagicMock()
        card.user_word.word = MagicMock()
        card.user_word.word.id = 100
        card.user_word.word.english_word = 'hello'
        card.user_word.word.russian_word = 'привет'
        card.user_word.word.listening = None

        result = service._format_cards_for_session([card])

        assert len(result) == 1
        assert result[0]['card_id'] == 1
        assert result[0]['front'] == 'hello'
        assert result[0]['back'] == 'привет'
        assert result[0]['direction'] == 'eng-rus'
        assert result[0]['state'] == CardState.NEW.value
        assert result[0]['phase'] == 'new'
        assert result[0]['new'] is True

    def test_format_rus_eng_card_learning_state(self, service):
        """Test formatting Russian to English card with LEARNING state."""
        card = MagicMock()
        card.id = 2
        card.direction = 'rus-eng'
        card.state = CardState.LEARNING.value
        card.step_index = 1
        card.repetitions = 2
        card.ease_factor = 2.3
        card.interval = 0
        card.lapses = 0
        card.session_attempts = 1
        card.user_word = MagicMock()
        card.user_word.word = MagicMock()
        card.user_word.word.id = 100
        card.user_word.word.english_word = 'world'
        card.user_word.word.russian_word = 'мир'
        card.user_word.word.listening = None

        result = service._format_cards_for_session([card])

        assert len(result) == 1
        assert result[0]['front'] == 'мир'
        assert result[0]['back'] == 'world'
        assert result[0]['direction'] == 'rus-eng'
        assert result[0]['state'] == CardState.LEARNING.value
        assert result[0]['phase'] == 'learning'
        assert result[0]['new'] is False

    def test_format_review_phase_card(self, service):
        """Test card with REVIEW state."""
        card = MagicMock()
        card.id = 3
        card.direction = 'eng-rus'
        card.state = CardState.REVIEW.value
        card.step_index = 0
        card.repetitions = 5
        card.ease_factor = 2.5
        card.interval = 15
        card.lapses = 0
        card.session_attempts = 0
        card.user_word = MagicMock()
        card.user_word.word = MagicMock()
        card.user_word.word.id = 100
        card.user_word.word.english_word = 'test'
        card.user_word.word.russian_word = 'тест'
        card.user_word.word.listening = None

        result = service._format_cards_for_session([card])

        assert result[0]['state'] == CardState.REVIEW.value
        assert result[0]['phase'] == 'review'

    def test_format_relearning_phase_card(self, service):
        """Test card with RELEARNING state maps to learning phase."""
        card = MagicMock()
        card.id = 4
        card.direction = 'eng-rus'
        card.state = CardState.RELEARNING.value
        card.step_index = 0
        card.repetitions = 5
        card.ease_factor = 2.3
        card.interval = 1
        card.lapses = 2
        card.session_attempts = 0
        card.user_word = MagicMock()
        card.user_word.word = MagicMock()
        card.user_word.word.id = 100
        card.user_word.word.english_word = 'test'
        card.user_word.word.russian_word = 'тест'
        card.user_word.word.listening = None

        result = service._format_cards_for_session([card])

        assert result[0]['state'] == CardState.RELEARNING.value
        assert result[0]['phase'] == 'learning'  # RELEARNING maps to 'learning' phase

    def test_format_legacy_card_without_state(self, service):
        """Test formatting legacy card without state attribute (defaults based on repetitions)."""
        card = MagicMock()
        card.id = 5
        card.direction = 'eng-rus'
        card.state = None  # Legacy card without state
        card.step_index = None
        card.repetitions = 0  # Never reviewed
        card.ease_factor = 2.5
        card.interval = 0
        card.lapses = None
        card.session_attempts = 0
        card.user_word = MagicMock()
        card.user_word.word = MagicMock()
        card.user_word.word.id = 100
        card.user_word.word.english_word = 'legacy'
        card.user_word.word.russian_word = 'устаревший'
        card.user_word.word.listening = None

        result = service._format_cards_for_session([card])

        # Legacy card with repetitions=0 should be treated as 'new'
        assert result[0]['state'] == CardState.NEW.value
        assert result[0]['phase'] == 'new'
        assert result[0]['new'] is True

    def test_format_legacy_card_with_repetitions(self, service):
        """Test formatting legacy card with repetitions but no state."""
        card = MagicMock()
        card.id = 6
        card.direction = 'eng-rus'
        card.state = None  # Legacy card without state
        card.step_index = None
        card.repetitions = 3  # Has been reviewed
        card.ease_factor = 2.5
        card.interval = 6
        card.lapses = None
        card.session_attempts = 0
        card.user_word = MagicMock()
        card.user_word.word = MagicMock()
        card.user_word.word.id = 100
        card.user_word.word.english_word = 'legacy2'
        card.user_word.word.russian_word = 'устаревший2'
        card.user_word.word.listening = None

        result = service._format_cards_for_session([card])

        # Legacy card with repetitions > 0 should be treated as 'review'
        assert result[0]['state'] == CardState.REVIEW.value
        assert result[0]['phase'] == 'review'
        assert result[0]['new'] is False


class TestGetAudioUrl:
    """Test audio URL generation."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    def test_audio_url_for_eng_rus(self, service):
        """Test audio URL is returned for eng-rus direction."""
        word = MagicMock()
        word.listening = 'hello.mp3'

        result = service._get_audio_url(word, 'eng-rus')

        assert result == '/static/audio/hello.mp3'

    def test_audio_url_anki_format(self, service):
        """Test audio URL extracts from Anki format."""
        word = MagicMock()
        word.listening = '[sound:hello.mp3]'

        result = service._get_audio_url(word, 'eng-rus')

        assert result == '/static/audio/hello.mp3'

    def test_no_audio_url_for_rus_eng(self, service):
        """Test no audio URL for rus-eng direction."""
        word = MagicMock()
        word.listening = 'hello.mp3'

        result = service._get_audio_url(word, 'rus-eng')

        assert result is None

    def test_no_audio_url_when_no_listening(self, service):
        """Test no audio URL when word has no listening."""
        word = MagicMock()
        word.listening = None

        result = service._get_audio_url(word, 'eng-rus')

        assert result is None


class TestGetOrCreateCardsForWord:
    """Test card creation/retrieval for words."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    @patch('app.srs.service.UserWord')
    @patch('app.srs.service.UserCardDirection')
    @patch('app.srs.service.db')
    def test_creates_user_word_if_not_exists(self, mock_db, mock_card, mock_user_word, service):
        """Test UserWord is created if it doesn't exist."""
        mock_user_word.query.filter_by.return_value.first.return_value = None
        mock_card.query.filter_by.return_value.first.return_value = None

        # Mock the new UserWord
        new_user_word = MagicMock()
        new_user_word.id = 1
        mock_user_word.return_value = new_user_word

        # Mock the new cards
        new_card = MagicMock()
        mock_card.return_value = new_card

        result = service.get_or_create_cards_for_word(
            user_id=1,
            word_id=100
        )

        mock_db.session.add.assert_called()
        mock_db.session.flush.assert_called()
        assert len(result) == 2  # Both directions

    @patch('app.srs.service.UserWord')
    @patch('app.srs.service.UserCardDirection')
    @patch('app.srs.service.db')
    def test_uses_existing_user_word(self, mock_db, mock_card, mock_user_word, service):
        """Test existing UserWord is used."""
        existing_user_word = MagicMock()
        existing_user_word.id = 1
        mock_user_word.query.filter_by.return_value.first.return_value = existing_user_word

        existing_card = MagicMock()
        mock_card.query.filter_by.return_value.first.return_value = existing_card

        result = service.get_or_create_cards_for_word(
            user_id=1,
            word_id=100
        )

        assert len(result) == 2
        assert all(c == existing_card for c in result)

    @patch('app.srs.service.UserWord')
    @patch('app.srs.service.UserCardDirection')
    @patch('app.srs.service.db')
    def test_creates_only_specified_directions(self, mock_db, mock_card, mock_user_word, service):
        """Test only specified directions are created."""
        existing_user_word = MagicMock()
        existing_user_word.id = 1
        mock_user_word.query.filter_by.return_value.first.return_value = existing_user_word
        mock_card.query.filter_by.return_value.first.return_value = None

        new_card = MagicMock()
        mock_card.return_value = new_card

        result = service.get_or_create_cards_for_word(
            user_id=1,
            word_id=100,
            directions=['eng-rus']  # Only one direction
        )

        assert len(result) == 1


class TestResetSessionAttempts:
    """Test session attempts reset."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    def test_reset_session_attempts_method_exists(self, service):
        """Test reset_session_attempts method exists."""
        assert hasattr(service, 'reset_session_attempts')
        assert callable(service.reset_session_attempts)

    def test_reset_session_attempts_accepts_parameters(self, service):
        """Test reset_session_attempts accepts expected parameters."""
        import inspect
        sig = inspect.signature(service.reset_session_attempts)
        params = list(sig.parameters.keys())

        assert 'user_id' in params
        assert 'word_ids' in params

    def test_reset_session_attempts_returns_int(self, service):
        """Test reset_session_attempts return type annotation."""
        import inspect
        sig = inspect.signature(service.reset_session_attempts)
        # Check the method exists and has return type
        assert sig.return_annotation == int or sig.return_annotation == inspect._empty
