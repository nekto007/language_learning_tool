"""Tests for SRSService"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, UTC, timedelta
from app.curriculum.services.srs_service import SRSService


@pytest.fixture
def card_lesson():
    """Create mock card lesson"""
    lesson = Mock()
    lesson.id = 1
    lesson.type = 'card'
    lesson.collection_id = 10
    lesson.get_srs_settings.return_value = {'new_cards_limit': 10}
    return lesson


@pytest.fixture
def mock_word():
    """Create mock word"""
    word = Mock()
    word.id = 1
    word.english_word = 'hello'
    word.russian_word = 'привет'
    word.audio_url = 'http://example.com/hello.mp3'
    return word


@pytest.fixture
def mock_user_word():
    """Create mock user word"""
    user_word = Mock()
    user_word.id = 1
    user_word.user_id = 1
    user_word.word_id = 1
    user_word.status = 'learning'
    return user_word


@pytest.fixture
def mock_card_direction():
    """Create mock card direction"""
    card_dir = Mock()
    card_dir.id = 1
    card_dir.user_word_id = 1
    card_dir.direction = 'eng-rus'
    card_dir.repetitions = 5
    card_dir.ease_factor = 2.5
    card_dir.interval = 7
    card_dir.next_review = datetime.now(UTC) - timedelta(days=1)  # Due
    card_dir.session_attempts = 0
    card_dir.correct_count = 10
    card_dir.incorrect_count = 2
    return card_dir


class TestGetCardsForLesson:
    """Test get_cards_for_lesson method"""

    def test_non_card_lesson_raises_error(self):
        """Test with non-card lesson type"""
        lesson = Mock()
        lesson.type = 'quiz'

        result = SRSService.get_cards_for_lesson(lesson, 1)

        assert result['total_due'] == 0
        assert result['cards'] == []

    @patch('app.curriculum.services.srs_service.CollectionWordLink')
    def test_no_collection_returns_empty(self, mock_link, card_lesson):
        """Test with no collection ID"""
        card_lesson.collection_id = None

        result = SRSService.get_cards_for_lesson(card_lesson, 1)

        assert result['total_due'] == 0
        assert result['new_cards'] == 0
        assert result['review_cards'] == 0

    @patch('app.curriculum.services.srs_service.db.session')
    @patch('app.curriculum.services.srs_service.UserCardDirection')
    @patch('app.curriculum.services.srs_service.UserWord')
    @patch('app.curriculum.services.srs_service.CollectionWordLink')
    def test_creates_new_cards_for_new_words(self, mock_link, mock_user_word_model, mock_card_dir_model, mock_session, card_lesson, mock_user_word):
        """Test creating new card directions for new words"""
        # Mock word links
        link = Mock(word_id=1)
        mock_link.query.filter_by.return_value.all.return_value = [link]

        # Mock user word
        mock_user_word_model.get_or_create.return_value = mock_user_word

        # Create mock new card direction instances
        new_card = Mock()
        new_card.repetitions = 0
        mock_card_dir_model.return_value = new_card

        # Mock no existing card direction (so new ones get created)
        mock_card_dir_model.query.filter_by.return_value.first.return_value = None

        result = SRSService.get_cards_for_lesson(card_lesson, 1)

        # Should create 2 new cards (eng-rus and rus-eng)
        assert result['new_cards'] == 2
        assert result['review_cards'] == 0
        assert len(result['cards']) == 2

    @patch('app.curriculum.services.srs_service.db.session')
    @patch('app.curriculum.services.srs_service.UserCardDirection')
    @patch('app.curriculum.services.srs_service.UserWord')
    @patch('app.curriculum.services.srs_service.CollectionWordLink')
    def test_identifies_due_review_cards(self, mock_link, mock_user_word_model, mock_card_dir_model, mock_session, card_lesson, mock_user_word, mock_card_direction):
        """Test identifying cards due for review"""
        link = Mock(word_id=1)
        mock_link.query.filter_by.return_value.all.return_value = [link]

        mock_user_word_model.get_or_create.return_value = mock_user_word

        # Mock existing card direction that's due
        mock_card_direction.next_review = datetime.now(UTC) - timedelta(hours=1)
        mock_card_dir_model.query.filter_by.return_value.first.return_value = mock_card_direction

        result = SRSService.get_cards_for_lesson(card_lesson, 1)

        assert result['review_cards'] == 2  # Both directions due

    @patch('app.curriculum.services.srs_service.db.session')
    @patch('app.curriculum.services.srs_service.UserCardDirection')
    @patch('app.curriculum.services.srs_service.UserWord')
    @patch('app.curriculum.services.srs_service.CollectionWordLink')
    def test_respects_new_cards_limit(self, mock_link, mock_user_word_model, mock_card_dir_model, mock_session, card_lesson):
        """Test that new cards limit is respected"""
        # Create 10 words (20 cards total - 2 directions each)
        links = [Mock(word_id=i) for i in range(1, 11)]
        mock_link.query.filter_by.return_value.all.return_value = links

        user_words = [Mock(id=i, user_id=1, word_id=i) for i in range(1, 11)]
        mock_user_word_model.get_or_create.side_effect = user_words

        # Create mock new card instances
        new_card = Mock(repetitions=0)
        mock_card_dir_model.return_value = new_card

        # All new cards (no existing directions)
        mock_card_dir_model.query.filter_by.return_value.first.return_value = None

        card_lesson.get_srs_settings.return_value = {'new_cards_limit': 5}

        result = SRSService.get_cards_for_lesson(card_lesson, 1)

        # Should limit to 5 new cards even though 20 are available
        assert result['total_due'] == 5


class TestGetCardSessionForLesson:
    """Test get_card_session_for_lesson method"""

    @patch('app.curriculum.services.srs_service.SRSService.get_cards_for_lesson')
    def test_no_cards_returns_completed(self, mock_get_cards, card_lesson):
        """Test with no due cards"""
        mock_get_cards.return_value = {
            'total_due': 0,
            'new_cards': 0,
            'review_cards': 0,
            'cards': []
        }

        result = SRSService.get_card_session_for_lesson(card_lesson, 1)

        assert result['total_cards'] == 0
        assert result['completed'] is True
        assert result['cards'] == []

    @patch('app.curriculum.services.srs_service.CollectionWords')
    @patch('app.curriculum.services.srs_service.UserWord')
    @patch('app.curriculum.services.srs_service.SRSService.get_cards_for_lesson')
    def test_prepares_cards_for_frontend(self, mock_get_cards, mock_user_word_model, mock_word_model, card_lesson, mock_card_direction, mock_user_word, mock_word):
        """Test card data preparation"""
        mock_get_cards.return_value = {
            'total_due': 1,
            'new_cards': 0,
            'review_cards': 1,
            'cards': [mock_card_direction],
            'srs_settings': {'new_cards_limit': 10}
        }

        mock_user_word_model.query.get.return_value = mock_user_word
        mock_word_model.query.get.return_value = mock_word

        result = SRSService.get_card_session_for_lesson(card_lesson, 1)

        assert result['total_cards'] == 1
        assert result['completed'] is False
        assert len(result['cards']) == 1

        card = result['cards'][0]
        assert card['word_id'] == 1
        assert card['front'] == 'hello'
        assert card['back'] == 'привет'
        assert card['direction'] == 'eng-rus'
        assert card['is_new'] is False  # repetitions = 5

    @patch('app.curriculum.services.srs_service.CollectionWords')
    @patch('app.curriculum.services.srs_service.UserWord')
    @patch('app.curriculum.services.srs_service.SRSService.get_cards_for_lesson')
    def test_handles_rus_eng_direction(self, mock_get_cards, mock_user_word_model, mock_word_model, card_lesson, mock_card_direction, mock_user_word, mock_word):
        """Test Russian to English direction"""
        mock_card_direction.direction = 'rus-eng'

        mock_get_cards.return_value = {
            'total_due': 1,
            'new_cards': 1,
            'review_cards': 0,
            'cards': [mock_card_direction],
            'srs_settings': {}
        }

        mock_user_word_model.query.get.return_value = mock_user_word
        mock_word_model.query.get.return_value = mock_word

        result = SRSService.get_card_session_for_lesson(card_lesson, 1)

        card = result['cards'][0]
        assert card['front'] == 'привет'
        assert card['back'] == 'hello'
        assert card['audio_url'] is None  # No audio for rus-eng direction


class TestProcessCardReview:
    """Test process_card_review method"""

    @patch('app.curriculum.services.srs_service.UserWord')
    def test_user_word_not_found(self, mock_user_word_model):
        """Test when user word doesn't exist"""
        mock_user_word_model.query.filter_by.return_value.first.return_value = None

        result = SRSService.process_card_review(1, 1, 1, 'eng-rus', 3)

        assert result['success'] is False
        assert 'error' in result

    @patch('app.curriculum.services.srs_service.UserCardDirection')
    @patch('app.curriculum.services.srs_service.UserWord')
    def test_card_direction_not_found(self, mock_user_word_model, mock_card_dir_model, mock_user_word):
        """Test when card direction doesn't exist"""
        mock_user_word_model.query.filter_by.return_value.first.return_value = mock_user_word
        mock_card_dir_model.query.filter_by.return_value.first.return_value = None

        result = SRSService.process_card_review(1, 1, 1, 'eng-rus', 3)

        assert result['success'] is False
        assert result['error'] == 'Card direction not found'

    @patch('app.curriculum.services.srs_service.db.session')
    @patch('app.curriculum.services.srs_service.SRSService.get_cards_for_lesson')
    @patch('app.curriculum.services.srs_service.Lessons')
    @patch('app.curriculum.services.srs_service.UserCardDirection')
    @patch('app.curriculum.services.srs_service.UserWord')
    def test_updates_card_interval(self, mock_user_word_model, mock_card_dir_model, mock_lessons_model, mock_get_cards, mock_session, mock_user_word, mock_card_direction):
        """Test updating card interval after review"""
        mock_user_word_model.query.filter_by.return_value.first.return_value = mock_user_word
        mock_card_dir_model.query.filter_by.return_value.first.return_value = mock_card_direction

        # Mock update method
        mock_card_direction.update_after_review.return_value = 14  # New interval

        mock_lesson = Mock()
        mock_lessons_model.query.get.return_value = mock_lesson

        mock_get_cards.return_value = {'total_due': 5}

        result = SRSService.process_card_review(1, 1, 1, 'eng-rus', 4)

        assert result['success'] is True
        assert result['old_interval'] == 7
        assert result['new_interval'] == 14
        assert result['lesson_complete'] is False
        assert result['remaining_cards'] == 5
        mock_card_direction.update_after_review.assert_called_once_with(4)

    @patch('app.curriculum.services.progress_service.ProgressService')
    @patch('app.curriculum.services.srs_service.db.session')
    @patch('app.curriculum.services.srs_service.SRSService.get_cards_for_lesson')
    @patch('app.curriculum.services.srs_service.Lessons')
    @patch('app.curriculum.services.srs_service.UserCardDirection')
    @patch('app.curriculum.services.srs_service.UserWord')
    def test_marks_lesson_complete_when_no_cards_due(self, mock_user_word_model, mock_card_dir_model, mock_lessons_model, mock_get_cards, mock_session, mock_progress, mock_user_word, mock_card_direction):
        """Test marking lesson as complete"""
        mock_user_word_model.query.filter_by.return_value.first.return_value = mock_user_word
        mock_card_dir_model.query.filter_by.return_value.first.return_value = mock_card_direction

        mock_card_direction.update_after_review.return_value = 14

        mock_lesson = Mock()
        mock_lessons_model.query.get.return_value = mock_lesson

        # No cards remaining
        mock_get_cards.return_value = {'total_due': 0}

        result = SRSService.process_card_review(1, 1, 1, 'eng-rus', 5)

        assert result['lesson_complete'] is True
        mock_progress.create_or_update_progress.assert_called_once()

    @patch('app.curriculum.services.srs_service.db.session')
    @patch('app.curriculum.services.srs_service.UserCardDirection')
    @patch('app.curriculum.services.srs_service.UserWord')
    def test_rolls_back_on_error(self, mock_user_word_model, mock_card_dir_model, mock_session, mock_user_word):
        """Test rollback on database error"""
        mock_user_word_model.query.filter_by.return_value.first.return_value = mock_user_word
        mock_card_dir_model.query.filter_by.side_effect = Exception('Database error')

        result = SRSService.process_card_review(1, 1, 1, 'eng-rus', 3)

        assert result['success'] is False
        mock_session.rollback.assert_called_once()


class TestGetUserSRSStatistics:
    """Test get_user_srs_statistics method"""

    @patch('app.curriculum.services.srs_service.UserWord')
    def test_handles_no_words(self, mock_user_word_model):
        """Test with no user words"""
        mock_user_word_model.query.filter_by.return_value.all.return_value = []

        result = SRSService.get_user_srs_statistics(1)

        assert result['total_words'] == 0
        assert result['retention_rate'] == 0

    @patch('app.curriculum.services.srs_service.UserWord')
    def test_handles_exceptions(self, mock_user_word_model):
        """Test exception handling"""
        mock_user_word_model.query.filter_by.side_effect = Exception('Database error')

        result = SRSService.get_user_srs_statistics(1)

        assert result['total_words'] == 0
        assert result['due_cards'] == 0
