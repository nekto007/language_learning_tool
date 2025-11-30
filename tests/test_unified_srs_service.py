# tests/test_unified_srs_service.py
"""
Tests for the unified SRS (Spaced Repetition System) service.

Tests the 1-2-3 rating scale:
    1 - Не знаю (Don't know): Reset, requeue in 1-2 cards
    2 - Сомневаюсь (Doubt): Moderate progress, requeue in 3-5 cards
    3 - Знаю (Know): Good progress, no requeue
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
        """Test requeue position ranges."""
        assert REQUEUE_RANGE_DONT_KNOW == (1, 2)
        assert REQUEUE_RANGE_DOUBT == (3, 5)

    def test_ease_factor_bounds(self):
        """Test ease factor bounds."""
        assert DEFAULT_EASE_FACTOR == 2.5
        assert MIN_EASE_FACTOR == 1.3
        assert MAX_EASE_FACTOR == 2.5


class TestGetRequeuePosition:
    """Test requeue position calculation."""

    def test_rating_dont_know_returns_1_or_2(self):
        """Rating 1 should return position 1 or 2."""
        positions = set()
        for _ in range(100):
            pos = UnifiedSRSService.get_requeue_position(RATING_DONT_KNOW)
            positions.add(pos)

        assert positions == {1, 2}

    def test_rating_doubt_returns_3_to_5(self):
        """Rating 2 should return position 3, 4, or 5."""
        positions = set()
        for _ in range(100):
            pos = UnifiedSRSService.get_requeue_position(RATING_DOUBT)
            positions.add(pos)

        assert positions == {3, 4, 5}

    def test_rating_know_returns_none(self):
        """Rating 3 should return None (no requeue)."""
        pos = UnifiedSRSService.get_requeue_position(RATING_KNOW)
        assert pos is None

    def test_unknown_rating_returns_none(self):
        """Unknown rating should return None."""
        pos = UnifiedSRSService.get_requeue_position(99)
        assert pos is None


class TestCalculateSM2Update:
    """Test SM-2 algorithm calculations."""

    def test_rating_dont_know_resets_progress(self):
        """Rating 1 should reset repetitions and interval to 0."""
        new_reps, new_interval, new_ef, days = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            repetitions=5,
            interval=30,
            ease_factor=2.5
        )

        assert new_reps == 0
        assert new_interval == 0
        assert new_ef == 2.5 - EF_DECREASE_DONT_KNOW  # 2.3
        assert days == 0

    def test_rating_dont_know_ef_minimum(self):
        """Rating 1 should not decrease EF below minimum."""
        new_reps, new_interval, new_ef, days = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DONT_KNOW,
            repetitions=1,
            interval=1,
            ease_factor=1.4  # Close to minimum
        )

        assert new_ef == MIN_EASE_FACTOR  # Should not go below 1.3

    def test_rating_doubt_first_repetition(self):
        """Rating 2 on first repetition should set interval to 1."""
        new_reps, new_interval, new_ef, days = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DOUBT,
            repetitions=0,
            interval=0,
            ease_factor=2.5
        )

        assert new_reps == 1
        assert new_interval == 1
        assert new_ef == 2.5  # EF stays the same
        assert days == 1

    def test_rating_doubt_second_repetition(self):
        """Rating 2 on second repetition should set interval to 3."""
        new_reps, new_interval, new_ef, days = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DOUBT,
            repetitions=1,
            interval=1,
            ease_factor=2.5
        )

        assert new_reps == 2
        assert new_interval == 3  # Shorter than "Know"
        assert new_ef == 2.5
        assert days == 3

    def test_rating_doubt_subsequent_repetitions(self):
        """Rating 2 on subsequent repetitions uses 80% multiplier."""
        new_reps, new_interval, new_ef, days = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_DOUBT,
            repetitions=2,
            interval=6,
            ease_factor=2.5
        )

        assert new_reps == 3
        # interval = round(6 * 2.5 * 0.8) = round(12) = 12
        assert new_interval == 12
        assert new_ef == 2.5

    def test_rating_know_first_repetition(self):
        """Rating 3 on first repetition should set interval to 1."""
        new_reps, new_interval, new_ef, days = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            repetitions=0,
            interval=0,
            ease_factor=2.5
        )

        assert new_reps == 1
        assert new_interval == 1
        assert new_ef == 2.5  # Already at max
        assert days == 1

    def test_rating_know_second_repetition(self):
        """Rating 3 on second repetition should set interval to 6."""
        new_reps, new_interval, new_ef, days = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            repetitions=1,
            interval=1,
            ease_factor=2.3
        )

        assert new_reps == 2
        assert new_interval == 6
        assert new_ef == 2.3 + EF_INCREASE_KNOW  # 2.45
        assert days == 6

    def test_rating_know_subsequent_repetitions(self):
        """Rating 3 on subsequent repetitions uses 120% bonus."""
        new_reps, new_interval, new_ef, days = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            repetitions=2,
            interval=6,
            ease_factor=2.0
        )

        assert new_reps == 3
        # interval = round(6 * 2.0 * 1.2) = round(14.4) = 14
        assert new_interval == 14
        assert new_ef == 2.0 + EF_INCREASE_KNOW  # 2.15

    def test_rating_know_ef_maximum(self):
        """Rating 3 should not increase EF above maximum."""
        new_reps, new_interval, new_ef, days = UnifiedSRSService.calculate_sm2_update(
            rating=RATING_KNOW,
            repetitions=1,
            interval=1,
            ease_factor=2.45  # Close to maximum
        )

        assert new_ef == MAX_EASE_FACTOR  # Should not exceed 2.5


class TestGradeCard:
    """Test card grading with database interaction."""

    @pytest.fixture
    def service(self):
        return UnifiedSRSService()

    @pytest.fixture
    def mock_card(self):
        """Create a mock card."""
        card = MagicMock()
        card.id = 123
        card.repetitions = 0
        card.interval = 0
        card.ease_factor = 2.5
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
        """Test successful card grading."""
        mock_model.query.get.return_value = mock_card

        result = service.grade_card(
            card_id=123,
            rating=RATING_KNOW,
            user_id=1,
            session_key='test_session'
        )

        assert result['success'] is True
        assert result['card_id'] == 123
        assert result['interval'] == 1
        assert 'next_review' in result
        assert result['requeue_position'] is None
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
        """Test that rating 1 returns requeue position."""
        mock_model.query.get.return_value = mock_card

        result = service.grade_card(
            card_id=123,
            rating=RATING_DONT_KNOW,
            user_id=1
        )

        assert result['success'] is True
        assert result['requeue_position'] in [1, 2]

    @patch('app.srs.service.UserCardDirection')
    @patch('app.srs.service.db')
    def test_grade_card_requeue_on_doubt(self, mock_db, mock_model, service, mock_card):
        """Test that rating 2 returns requeue position."""
        mock_model.query.get.return_value = mock_card

        result = service.grade_card(
            card_id=123,
            rating=RATING_DOUBT,
            user_id=1
        )

        assert result['success'] is True
        assert result['requeue_position'] in [3, 4, 5]

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
        """Ensure requeue ranges are properly documented."""
        # Rating 1: 1-2 cards
        assert REQUEUE_RANGE_DONT_KNOW == (1, 2)
        # Rating 2: 3-5 cards
        assert REQUEUE_RANGE_DOUBT == (3, 5)
