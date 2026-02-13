"""Tests for BookSRSIntegration"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone, timedelta, UTC
from app.curriculum.services.book_srs_integration import BookSRSIntegration


@pytest.fixture
def integration():
    """Create BookSRSIntegration instance"""
    return BookSRSIntegration()


@pytest.fixture
def daily_lesson():
    """Create mock daily lesson"""
    lesson = Mock()
    lesson.id = 1
    lesson.lesson_type = 'vocabulary'
    return lesson


@pytest.fixture
def mock_word():
    """Create mock word"""
    word = Mock()
    word.id = 1
    word.english_word = 'hello'
    word.russian_word = 'привет'
    word.get_download = 1
    word.listening = 'hello.mp3'
    word.examples = None  # Prevent Mock from returning Mock object for 'in' check
    word.sentences = None  # Accessed by _format_deck_for_session
    return word


@pytest.fixture
def mock_user_word():
    """Create mock user word"""
    user_word = Mock()
    user_word.id = 1
    user_word.user_id = 1
    user_word.word_id = 1
    return user_word


@pytest.fixture
def mock_card():
    """Create mock card direction"""
    card = Mock()
    card.id = 1
    card.user_word_id = 1
    card.direction = 'eng-rus'
    card.repetitions = 5
    card.ease_factor = 2.5
    card.interval = 7
    card.next_review = datetime.now(timezone.utc) - timedelta(days=1)
    # Create word mock with examples=None, sentences=None to prevent 'in' check error
    word_mock = Mock(english_word='test', russian_word='тест', examples=None, sentences=None)
    card.user_word = Mock(user_id=1, word=word_mock)
    return card


class TestCreateSRSSessionForLesson:
    """Test create_srs_session_for_lesson method"""

    @patch('app.curriculum.services.book_srs_integration.db.session')
    @patch.object(BookSRSIntegration, '_format_deck_for_session')
    @patch.object(BookSRSIntegration, '_filter_due_cards')
    @patch.object(BookSRSIntegration, '_get_or_create_srs_cards')
    @patch.object(BookSRSIntegration, '_get_vocabulary_words_for_lesson')
    def test_creates_session_with_cards(self, mock_get_vocab, mock_get_cards, mock_filter, mock_format, mock_db, integration, daily_lesson):
        """Test creating SRS session"""
        mock_word_data = {'word': Mock(id=1), 'context': 'Test', 'frequency': 5, 'word_id': 1}
        mock_get_vocab.return_value = [mock_word_data]

        # Cards with context dict structure, including direction and last_reviewed
        mock_card = Mock(direction='eng-rus', last_reviewed=None)
        mock_get_cards.return_value = [{'card': mock_card, 'context': 'Test'}]
        mock_filter.return_value = [{'card': mock_card, 'context': 'Test'}]

        deck_item = {'card_id': 1, 'front': 'hello', 'back': 'привет'}
        mock_format.return_value = [deck_item]

        enrollment = Mock()
        result = integration.create_srs_session_for_lesson(1, daily_lesson, enrollment)

        assert result['total_cards'] == 1
        assert result['lesson_id'] == 1
        assert len(result['deck']) == 1
        assert result['session_key'] is not None

    @patch.object(BookSRSIntegration, '_get_vocabulary_words_for_lesson')
    def test_returns_empty_when_no_vocabulary(self, mock_get_vocab, integration, daily_lesson):
        """Test with no vocabulary words"""
        mock_get_vocab.return_value = []

        enrollment = Mock()
        result = integration.create_srs_session_for_lesson(1, daily_lesson, enrollment)

        assert result['deck'] == []
        assert result['session_key'] is None

    @patch('app.curriculum.services.book_srs_integration.db.session')
    @patch.object(BookSRSIntegration, '_format_deck_for_session')
    @patch.object(BookSRSIntegration, '_filter_due_cards')
    @patch.object(BookSRSIntegration, '_get_or_create_srs_cards')
    @patch.object(BookSRSIntegration, '_get_vocabulary_words_for_lesson')
    def test_limits_to_25_cards_when_over_50(self, mock_get_vocab, mock_get_cards, mock_filter, mock_format, mock_db, integration, daily_lesson):
        """Test card limit when >50 due cards"""
        mock_get_vocab.return_value = [{'word': Mock(id=i), 'context': None, 'frequency': 1, 'word_id': i} for i in range(60)]
        mock_cards = [{'card': Mock(direction='eng-rus', last_reviewed=None), 'context': None} for _ in range(60)]
        mock_get_cards.return_value = mock_cards
        mock_filter.return_value = mock_cards
        mock_format.return_value = [{'card_id': i} for i in range(25)]

        enrollment = Mock()
        result = integration.create_srs_session_for_lesson(1, daily_lesson, enrollment)

        # Should be called with limited cards
        assert mock_format.call_args[0][0].__len__() <= 25


class TestGetVocabularyWordsForLesson:
    """Test _get_vocabulary_words_for_lesson method"""

    @patch('app.curriculum.services.book_srs_integration.SliceVocabulary')
    def test_retrieves_vocabulary_words(self, mock_slice, integration, daily_lesson):
        """Test retrieving vocabulary words from lesson"""
        # Mock entries with word objects and required fields
        word1 = Mock(id=1, english_word='hello')
        word2 = Mock(id=2, english_word='world')
        entry1 = Mock(word=word1, word_id=1, context_sentence='Hello context', frequency_in_slice=10)
        entry2 = Mock(word=word2, word_id=2, context_sentence='World context', frequency_in_slice=5)

        query_mock = Mock()
        mock_slice.query = query_mock
        query_mock.filter_by.return_value.join.return_value.order_by.return_value.all.return_value = [entry1, entry2]

        # daily_lesson needs module attribute for the fallback logic
        daily_lesson.module = None

        result = integration._get_vocabulary_words_for_lesson(daily_lesson)

        assert len(result) == 2
        # Result is now a list of dicts with 'word' key
        assert result[0]['word'].english_word == 'hello'
        assert result[0]['context'] == 'Hello context'

    @patch('app.curriculum.services.book_srs_integration.SliceVocabulary')
    def test_limits_to_target_count(self, mock_slice, integration, daily_lesson):
        """Test target_count limit (default 10)"""
        # Create 15 mock entries
        mock_entries = []
        for i in range(15):
            word = Mock(id=i, english_word=f'word{i}')
            entry = Mock(word=word, word_id=i, context_sentence=f'Context {i}', frequency_in_slice=15-i)
            mock_entries.append(entry)

        query_mock = Mock()
        mock_slice.query = query_mock
        query_mock.filter_by.return_value.join.return_value.order_by.return_value.all.return_value = mock_entries

        # daily_lesson needs module attribute
        daily_lesson.module = None

        result = integration._get_vocabulary_words_for_lesson(daily_lesson, target_count=10)

        # Should return only 10 words (target_count)
        assert len(result) == 10


class TestGetOrCreateSRSCards:
    """Test _get_or_create_srs_cards method"""

    @patch('app.curriculum.services.book_srs_integration.db.session')
    @patch.object(BookSRSIntegration, '_link_card_to_book_lesson')
    @patch.object(BookSRSIntegration, '_get_or_create_card_direction')
    @patch('app.curriculum.services.book_srs_integration.UserWord')
    def test_creates_cards_for_both_directions(self, mock_user_word_model, mock_get_card, mock_link, mock_session, integration, daily_lesson, mock_word, mock_user_word):
        """Test creating cards for both eng-rus and rus-eng"""
        mock_user_word_model.get_or_create.return_value = mock_user_word

        eng_card = Mock(id=1, direction='eng-rus')
        rus_card = Mock(id=2, direction='rus-eng')
        mock_get_card.side_effect = [eng_card, rus_card]

        # word_data_list is now a list of dicts with 'word' key
        word_data = {'word': mock_word, 'context': 'Test context', 'frequency': 10, 'word_id': mock_word.id}
        result = integration._get_or_create_srs_cards(1, [word_data], daily_lesson)

        assert len(result) == 2
        # Result is now list of dicts with 'card' key
        assert result[0]['card'].direction == 'eng-rus'
        assert result[1]['card'].direction == 'rus-eng'


class TestGetOrCreateCardDirection:
    """Test _get_or_create_card_direction method"""

    @patch('app.curriculum.services.book_srs_integration.db.session')
    @patch('app.curriculum.services.book_srs_integration.UserCardDirection')
    def test_creates_new_card(self, mock_card_model, mock_session, integration, mock_user_word):
        """Test creating new card direction"""
        mock_card_model.query.filter_by.return_value.first.return_value = None

        new_card = Mock()
        mock_card_model.return_value = new_card

        result = integration._get_or_create_card_direction(mock_user_word, 'eng-rus')

        assert result == new_card
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @patch('app.curriculum.services.book_srs_integration.UserCardDirection')
    def test_returns_existing_card(self, mock_card_model, integration, mock_user_word, mock_card):
        """Test returning existing card"""
        mock_card_model.query.filter_by.return_value.first.return_value = mock_card

        result = integration._get_or_create_card_direction(mock_user_word, 'eng-rus')

        assert result == mock_card


class TestFilterDueCards:
    """Test _filter_due_cards method"""

    def test_includes_new_cards(self, integration):
        """Test including new cards (repetitions=0)"""
        new_card = Mock(repetitions=0, next_review=None, direction='eng-rus')
        cards = [{'card': new_card, 'context': None}]

        result = integration._filter_due_cards(cards)

        assert len(result) == 1

    def test_includes_overdue_cards(self, integration):
        """Test including overdue cards"""
        overdue_card = Mock(
            repetitions=5,
            next_review=datetime.now(timezone.utc) - timedelta(hours=1),
            direction='eng-rus'
        )
        cards = [{'card': overdue_card, 'context': None}]

        result = integration._filter_due_cards(cards)

        assert len(result) == 1

    def test_excludes_future_cards(self, integration):
        """Test excluding cards due in future"""
        future_card = Mock(
            repetitions=3,
            next_review=datetime.now(timezone.utc) + timedelta(days=1),
            direction='eng-rus'
        )
        cards = [{'card': future_card, 'context': None}]

        result = integration._filter_due_cards(cards)

        assert len(result) == 0


class TestFormatDeckForSession:
    """Test _format_deck_for_session method"""

    def test_formats_eng_rus_card(self, integration, mock_word):
        """Test formatting eng-rus card"""
        card = Mock()
        card.id = 1
        card.direction = 'eng-rus'
        card.repetitions = 0
        card.ease_factor = 2.5
        card.interval = 0
        card.user_word = Mock(word=mock_word)

        # Input is now list of dicts with 'card' and 'context' keys
        cards_with_context = [{'card': card, 'context': 'Test context'}]

        with patch.object(integration, '_get_audio_url', return_value='audio.mp3'):
            result = integration._format_deck_for_session(cards_with_context)

        assert len(result) == 1
        assert result[0]['front'] == 'hello'
        assert result[0]['back'] == 'привет'
        assert result[0]['phase'] == 'new'
        assert result[0]['new'] is True
        assert result[0]['context'] == 'Test context'

    def test_formats_rus_eng_card(self, integration, mock_word):
        """Test formatting rus-eng card"""
        card = Mock()
        card.id = 1
        card.direction = 'rus-eng'
        card.repetitions = 5
        card.ease_factor = 2.5
        card.interval = 7
        card.user_word = Mock(word=mock_word)

        cards_with_context = [{'card': card, 'context': None}]

        with patch.object(integration, '_get_audio_url', return_value=None):
            result = integration._format_deck_for_session(cards_with_context)

        assert result[0]['front'] == 'привет'
        assert result[0]['back'] == 'hello'
        assert result[0]['phase'] == 'review'
        assert result[0]['new'] is False

    def test_determines_learning_phase(self, integration, mock_word):
        """Test learning phase determination"""
        card = Mock()
        card.id = 1
        card.direction = 'eng-rus'
        card.repetitions = 2
        card.ease_factor = 2.5
        card.interval = 1
        card.user_word = Mock(word=mock_word)

        cards_with_context = [{'card': card, 'context': None}]

        with patch.object(integration, '_get_audio_url', return_value=None):
            result = integration._format_deck_for_session(cards_with_context)

        assert result[0]['phase'] == 'learning'


class TestProcessCardGrade:
    """Test process_card_grade method"""

    @patch('app.curriculum.services.book_srs_integration.db.session')
    @patch.object(BookSRSIntegration, '_log_card_review')
    @patch('app.curriculum.services.book_srs_integration.UserCardDirection')
    def test_processes_grade_successfully(self, mock_card_model, mock_log, mock_session, integration, mock_card):
        """Test successful grade processing"""
        mock_card.update_after_review.return_value = 14
        mock_card.next_review = datetime.now(timezone.utc) + timedelta(days=14)
        mock_card_model.query.filter_by.return_value.first.return_value = mock_card

        result = integration.process_card_grade(1, 1, 4, 'session_123')

        assert result['success'] is True
        assert result['card_id'] == 1
        mock_card.update_after_review.assert_called_once_with(4)
        mock_session.commit.assert_called_once()

    @patch('app.curriculum.services.book_srs_integration.UserCardDirection')
    def test_rejects_unauthorized_access(self, mock_card_model, integration):
        """Test rejecting access to other user's card"""
        card = Mock(user_word=Mock(user_id=999))
        mock_card_model.query.filter_by.return_value.first.return_value = card

        result = integration.process_card_grade(1, 1, 4, 'session_123')

        assert result['success'] is False
        assert 'access denied' in result['error'].lower()

    @patch('app.curriculum.services.book_srs_integration.UserCardDirection')
    def test_handles_card_not_found(self, mock_card_model, integration):
        """Test handling non-existent card"""
        mock_card_model.query.filter_by.return_value.first.return_value = None

        result = integration.process_card_grade(1, 999, 4, 'session_123')

        assert result['success'] is False

    @patch('app.curriculum.services.book_srs_integration.db.session')
    @patch('app.curriculum.services.book_srs_integration.UserCardDirection')
    def test_rolls_back_on_error(self, mock_card_model, mock_session, integration, mock_card):
        """Test rollback on error"""
        mock_card_model.query.filter_by.return_value.first.return_value = mock_card
        mock_card.update_after_review.side_effect = Exception('Database error')

        result = integration.process_card_grade(1, 1, 4, 'session_123')

        assert result['success'] is False
        mock_session.rollback.assert_called_once()


class TestCompleteSRSSession:
    """Test complete_srs_session method"""

    @patch('app.curriculum.services.book_srs_integration.db.session')
    @patch('app.curriculum.services.book_srs_integration.LessonCompletionEvent')
    def test_creates_completion_event(self, mock_event_model, mock_session, integration):
        """Test creating completion event"""
        session_stats = {
            'cards_reviewed': 10,
            'correct_count': 8,
            'total_count': 10,
            'duration_seconds': 300
        }

        result = integration.complete_srs_session(1, 1, 'session_123', session_stats)

        assert result is True
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @patch('app.curriculum.services.book_srs_integration.db.session')
    @patch('app.curriculum.services.book_srs_integration.LessonCompletionEvent')
    def test_handles_error(self, mock_event_model, mock_session, integration):
        """Test error handling"""
        mock_session.add.side_effect = Exception('Database error')

        result = integration.complete_srs_session(1, 1, 'session_123', {})

        assert result is False
        mock_session.rollback.assert_called_once()


class TestAutoCreateSRSCards:
    """Test auto_create_srs_cards_from_vocabulary_lesson method"""

    @patch('app.curriculum.services.book_srs_integration.db.session')
    @patch.object(BookSRSIntegration, '_get_or_create_srs_cards')
    @patch.object(BookSRSIntegration, '_get_vocabulary_words_for_lesson')
    def test_creates_cards_for_vocabulary_lesson(self, mock_get_vocab, mock_create_cards, mock_session, integration, daily_lesson):
        """Test auto-creating cards for vocabulary lesson"""
        daily_lesson.lesson_type = 'vocabulary'
        mock_get_vocab.return_value = [Mock(id=1), Mock(id=2)]
        mock_create_cards.return_value = [Mock(), Mock(), Mock(), Mock()]

        result = integration.auto_create_srs_cards_from_vocabulary_lesson(1, daily_lesson)

        assert result is True
        mock_session.commit.assert_called_once()

    def test_skips_non_vocabulary_lessons(self, integration, daily_lesson):
        """Test skipping non-vocabulary lessons"""
        daily_lesson.lesson_type = 'reading'

        result = integration.auto_create_srs_cards_from_vocabulary_lesson(1, daily_lesson)

        assert result is False


class TestGetNextSRSSessionTime:
    """Test get_next_srs_session_time method"""

    @patch('app.curriculum.services.book_srs_integration.UserCardDirection')
    def test_returns_earliest_review_time(self, mock_card_model, integration):
        """Test returning earliest review time"""
        next_time = datetime.now(timezone.utc) + timedelta(hours=2)
        card = Mock(next_review=next_time)

        query_mock = Mock()
        mock_card_model.query = query_mock
        query_mock.join.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = card

        result = integration.get_next_srs_session_time(1, 1)

        assert result == next_time

    @patch('app.curriculum.services.book_srs_integration.UserCardDirection')
    def test_returns_none_when_no_cards(self, mock_card_model, integration):
        """Test returning None when no cards"""
        query_mock = Mock()
        mock_card_model.query = query_mock
        query_mock.join.return_value.filter.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = integration.get_next_srs_session_time(1, 1)

        assert result is None


class TestGetDueCardsCount:
    """Test get_due_cards_count method"""

    @patch('app.curriculum.services.book_srs_integration.UserCardDirection')
    def test_returns_zero_on_error(self, mock_card_model, integration):
        """Test returning 0 on error"""
        mock_card_model.query.join.side_effect = Exception('Database error')

        result = integration.get_due_cards_count(1)

        assert result == 0

    # Note: Actual count test omitted - too complex to mock SQLAlchemy query with db.or_
    # and model attribute comparisons. Tested via integration tests instead.
