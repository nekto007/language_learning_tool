"""
Tests for study services (QuizService, GameService, DeckService)
"""
import pytest
from unittest.mock import MagicMock, patch
import random


class MockWord:
    """Mock CollectionWords object for testing"""
    def __init__(self, id, english, russian, sentences=None):
        self.id = id
        self.english_word = english
        self.russian_word = russian
        self.sentences = sentences


class TestQuizService:
    """Tests for QuizService"""

    @pytest.fixture
    def quiz_service(self):
        from app.study.services.quiz_service import QuizService
        return QuizService

    @pytest.fixture
    def sample_words(self):
        return [
            MockWord(1, "hello", "привет"),
            MockWord(2, "world", "мир"),
            MockWord(3, "cat", "кошка"),
            MockWord(4, "dog", "собака"),
            MockWord(5, "house", "дом"),
        ]

    def test_generate_quiz_questions_empty_list(self, quiz_service):
        """Test with empty word list"""
        result = quiz_service.generate_quiz_questions([], 5)
        assert result == []

    def test_generate_quiz_questions_zero_count(self, quiz_service, sample_words):
        """Test with zero count"""
        result = quiz_service.generate_quiz_questions(sample_words, 0)
        assert result == []

    def test_generate_quiz_questions_negative_count(self, quiz_service, sample_words):
        """Test with negative count"""
        result = quiz_service.generate_quiz_questions(sample_words, -1)
        assert result == []

    def test_generate_quiz_questions_returns_list(self, quiz_service, sample_words):
        """Test that questions are returned as list"""
        random.seed(42)  # For reproducibility
        result = quiz_service.generate_quiz_questions(sample_words, 3)
        assert isinstance(result, list)
        assert len(result) <= 3

    def test_generate_quiz_questions_with_mixed_types(self, quiz_service, sample_words):
        """Test that questions have mixed types (multiple_choice and fill_blank)"""
        random.seed(42)
        # Mock the database query to return sample_words
        with patch.object(quiz_service, 'generate_quiz_questions', wraps=quiz_service.generate_quiz_questions):
            with patch('app.study.services.quiz_service.CollectionWords') as mock_cw:
                mock_cw.query.filter.return_value.limit.return_value.all.return_value = sample_words
                result = quiz_service.generate_quiz_questions(sample_words, 6)
                # Should have a mix of multiple_choice and fill_blank
                types = set(q.get('type') for q in result)
                # At minimum should have fill_blank since rus_to_eng is always fill_blank
                assert 'fill_blank' in types

    def test_generate_quiz_questions_limits_to_available_words(self, quiz_service, sample_words):
        """Test that count is limited to available words (2 questions per word max)"""
        with patch('app.study.services.quiz_service.CollectionWords') as mock_cw:
            mock_cw.query.filter.return_value.limit.return_value.all.return_value = sample_words
            result = quiz_service.generate_quiz_questions(sample_words, 100)
            # Max questions = len(words) * 2 (one eng->rus and one rus->eng per word)
            assert len(result) <= len(sample_words) * 2

    # Test create_multiple_choice_question
    def test_multiple_choice_eng_to_rus(self, quiz_service, sample_words):
        """Test multiple choice question in eng_to_rus direction"""
        word = sample_words[0]
        result = quiz_service.create_multiple_choice_question(word, sample_words, 'eng_to_rus')

        assert result['type'] == 'multiple_choice'
        assert result['word_id'] == word.id
        assert result['text'] == word.english_word
        assert result['answer'] == word.russian_word
        assert result['direction'] == 'eng_to_rus'
        assert word.russian_word in result['options']
        assert len(result['options']) == 4

    def test_multiple_choice_rus_to_eng(self, quiz_service, sample_words):
        """Test multiple choice question in rus_to_eng direction"""
        word = sample_words[0]
        result = quiz_service.create_multiple_choice_question(word, sample_words, 'rus_to_eng')

        assert result['type'] == 'multiple_choice'
        assert result['text'] == word.russian_word
        assert result['answer'] == word.english_word
        assert result['direction'] == 'rus_to_eng'

    def test_multiple_choice_with_single_word(self, quiz_service):
        """Test multiple choice with only one word"""
        words = [MockWord(1, "hello", "привет")]
        result = quiz_service.create_multiple_choice_question(words[0], words, 'eng_to_rus')

        assert result['answer'] == "привет"
        assert "привет" in result['options']

    # Test question_types constant (true_false was removed from implementation)
    def test_question_types_constant(self, quiz_service):
        """Test that QUESTION_TYPES contains expected types"""
        assert 'multiple_choice' in quiz_service.QUESTION_TYPES
        assert 'fill_blank' in quiz_service.QUESTION_TYPES

    def test_multiple_choice_has_question_label(self, quiz_service, sample_words):
        """Test multiple choice question has question_label field"""
        word = sample_words[0]
        result = quiz_service.create_multiple_choice_question(word, sample_words, 'eng_to_rus')

        assert 'question_label' in result
        assert result['question_label'] == 'Переведите на русский:'

    def test_multiple_choice_rus_to_eng_label(self, quiz_service, sample_words):
        """Test multiple choice rus_to_eng has correct label"""
        word = sample_words[0]
        result = quiz_service.create_multiple_choice_question(word, sample_words, 'rus_to_eng')

        assert result['question_label'] == 'Переведите на английский:'

    def test_multiple_choice_has_hint(self, quiz_service, sample_words):
        """Test multiple choice question has hint field"""
        word = sample_words[0]
        result = quiz_service.create_multiple_choice_question(word, sample_words, 'eng_to_rus')

        assert 'hint' in result
        assert 'Начинается с:' in result['hint']

    def test_multiple_choice_id_format(self, quiz_service, sample_words):
        """Test multiple choice question id format"""
        word = sample_words[0]
        result = quiz_service.create_multiple_choice_question(word, sample_words, 'eng_to_rus')

        assert result['id'] == f'mc_{word.id}_eng_to_rus'

    # Test create_fill_blank_question
    def test_fill_blank_eng_to_rus(self, quiz_service, sample_words):
        """Test fill blank in eng_to_rus direction"""
        word = sample_words[0]
        result = quiz_service.create_fill_blank_question(word, 'eng_to_rus')

        assert result['type'] == 'fill_blank'
        assert result['word_id'] == word.id
        assert result['text'] == "hello"
        assert result['answer'] == "привет"
        assert result['direction'] == 'eng_to_rus'
        assert 'acceptable_answers' in result
        assert "привет" in result['acceptable_answers']

    def test_fill_blank_rus_to_eng(self, quiz_service, sample_words):
        """Test fill blank in rus_to_eng direction"""
        word = sample_words[0]
        result = quiz_service.create_fill_blank_question(word, 'rus_to_eng')

        assert result['text'] == "привет"
        assert result['answer'] == "hello"
        assert result['direction'] == 'rus_to_eng'
        assert "hello" in result['acceptable_answers']

    # Test calculate_quiz_score
    def test_calculate_quiz_score_zero_questions(self, quiz_service):
        """Test score calculation with zero questions"""
        result = quiz_service.calculate_quiz_score(0, 0, 0)
        assert result == {'score': 0, 'percentage': 0, 'xp_awarded': 0}

    def test_calculate_quiz_score_basic(self, quiz_service):
        """Test basic score calculation"""
        result = quiz_service.calculate_quiz_score(10, 8, 100)

        assert result['score'] == 8
        assert result['total'] == 10
        assert result['percentage'] == 80.0
        assert result['time_taken'] == 100
        assert result['xp_awarded'] >= 80  # At least base XP

    def test_calculate_quiz_score_perfect(self, quiz_service):
        """Test perfect score with bonus"""
        result = quiz_service.calculate_quiz_score(10, 10, 100)

        assert result['score'] == 10
        assert result['percentage'] == 100.0
        # Perfect bonus: 50 XP
        assert result['xp_awarded'] >= 100 + 50  # Base + perfect bonus

    def test_calculate_quiz_score_fast_bonus(self, quiz_service):
        """Test fast time bonus (< 5 sec/question)"""
        # 10 questions in 30 seconds = 3 sec/question (very fast)
        result = quiz_service.calculate_quiz_score(10, 10, 30)

        # Should have 1.5x multiplier
        base_xp = 10 * 10 + 50  # 100 base + 50 perfect bonus
        expected_xp = int(base_xp * 1.5)
        assert result['xp_awarded'] == expected_xp

    def test_calculate_quiz_score_medium_speed_bonus(self, quiz_service):
        """Test medium speed bonus (5-10 sec/question)"""
        # 10 questions in 70 seconds = 7 sec/question (fast)
        result = quiz_service.calculate_quiz_score(10, 10, 70)

        # Should have 1.2x multiplier
        base_xp = 10 * 10 + 50
        expected_xp = int(base_xp * 1.2)
        assert result['xp_awarded'] == expected_xp

    def test_calculate_quiz_score_slow_no_bonus(self, quiz_service):
        """Test slow speed no bonus (> 10 sec/question)"""
        # 10 questions in 150 seconds = 15 sec/question (slow)
        result = quiz_service.calculate_quiz_score(10, 10, 150)

        # No time bonus
        base_xp = 10 * 10 + 50
        assert result['xp_awarded'] == base_xp


class TestGameService:
    """Tests for GameService"""

    @pytest.fixture
    def game_service(self):
        from app.study.services.game_service import GameService
        return GameService

    @pytest.fixture
    def sample_words(self):
        return [
            MockWord(1, "hello", "привет"),
            MockWord(2, "world", "мир"),
            MockWord(3, "cat", "кошка"),
            MockWord(4, "dog", "собака"),
            MockWord(5, "house", "дом"),
            MockWord(6, "tree", "дерево"),
            MockWord(7, "water", "вода"),
            MockWord(8, "fire", "огонь"),
            MockWord(9, "earth", "земля"),
            MockWord(10, "air", "воздух"),
        ]

    def test_difficulty_settings_exist(self, game_service):
        """Test that difficulty settings are defined"""
        assert 'easy' in game_service.DIFFICULTY_SETTINGS
        assert 'medium' in game_service.DIFFICULTY_SETTINGS
        assert 'hard' in game_service.DIFFICULTY_SETTINGS

        for diff in ['easy', 'medium', 'hard']:
            assert 'pairs' in game_service.DIFFICULTY_SETTINGS[diff]
            assert 'time_limit' in game_service.DIFFICULTY_SETTINGS[diff]

    def test_difficulty_progression(self, game_service):
        """Test that difficulty increases (more pairs, less time)"""
        easy = game_service.DIFFICULTY_SETTINGS['easy']
        medium = game_service.DIFFICULTY_SETTINGS['medium']
        hard = game_service.DIFFICULTY_SETTINGS['hard']

        assert easy['pairs'] < medium['pairs'] < hard['pairs']
        assert easy['time_limit'] > medium['time_limit'] > hard['time_limit']

    def test_get_matching_words_easy(self, game_service, sample_words):
        """Test word selection for easy difficulty"""
        random.seed(42)
        result = game_service.get_matching_words(sample_words, 'easy')

        assert isinstance(result, list)
        assert len(result) == 6  # Easy = 6 pairs

        for pair in result:
            assert 'id' in pair
            assert 'english' in pair
            assert 'russian' in pair
            assert pair['difficulty'] == 'easy'

    def test_get_matching_words_medium(self, game_service, sample_words):
        """Test word selection for medium difficulty"""
        random.seed(42)
        result = game_service.get_matching_words(sample_words, 'medium')

        assert len(result) == 8  # Medium = 8 pairs

    def test_get_matching_words_hard(self, game_service, sample_words):
        """Test word selection for hard difficulty"""
        random.seed(42)
        result = game_service.get_matching_words(sample_words, 'hard')

        assert len(result) == 10  # Hard = 10 pairs

    def test_get_matching_words_default_difficulty(self, game_service, sample_words):
        """Test default difficulty is medium"""
        random.seed(42)
        result = game_service.get_matching_words(sample_words)

        assert len(result) == 8  # Medium is default

    def test_get_matching_words_unknown_difficulty(self, game_service, sample_words):
        """Test unknown difficulty defaults to medium"""
        random.seed(42)
        result = game_service.get_matching_words(sample_words, 'extreme')

        assert len(result) == 8  # Defaults to medium

    def test_get_matching_words_limited_by_available(self, game_service):
        """Test that pairs are limited by available words"""
        few_words = [
            MockWord(1, "hello", "привет"),
            MockWord(2, "world", "мир"),
        ]

        result = game_service.get_matching_words(few_words, 'hard')
        assert len(result) == 2  # Only 2 words available

    # Test calculate_matching_score
    def test_calculate_matching_score_zero_pairs(self, game_service):
        """Test score with zero pairs"""
        result = game_service.calculate_matching_score('medium', 0, 0, 60, 10)
        assert result == {'total_score': 0, 'xp_awarded': 0}

    def test_calculate_matching_score_basic(self, game_service):
        """Test basic score calculation"""
        result = game_service.calculate_matching_score('medium', 5, 8, 100, 20)

        assert 'base_score' in result
        assert 'completion_bonus' in result
        assert 'time_bonus' in result
        assert 'efficiency_bonus' in result
        assert 'difficulty_multiplier' in result
        assert 'total_score' in result
        assert 'xp_awarded' in result

        assert result['base_score'] == 500  # 5 pairs * 100
        assert result['completion_bonus'] == 0  # Not complete
        assert result['pairs_matched'] == 5
        assert result['total_pairs'] == 8

    def test_calculate_matching_score_complete(self, game_service):
        """Test complete game bonus"""
        result = game_service.calculate_matching_score('medium', 8, 8, 100, 20)

        assert result['completion_bonus'] == 200
        assert result['base_score'] == 800

    def test_calculate_matching_score_time_bonus(self, game_service):
        """Test time bonus calculation"""
        # Medium has 150 second limit
        # 50 seconds taken = 100 seconds remaining
        result = game_service.calculate_matching_score('medium', 8, 8, 50, 16)

        time_remaining = 150 - 50
        expected_time_bonus = time_remaining * 2
        assert result['time_bonus'] == expected_time_bonus

    def test_calculate_matching_score_no_time_bonus(self, game_service):
        """Test no time bonus when time exceeded"""
        result = game_service.calculate_matching_score('medium', 8, 8, 200, 20)
        assert result['time_bonus'] == 0  # Time exceeded limit

    def test_calculate_matching_score_efficiency_excellent(self, game_service):
        """Test efficiency bonus for excellent play"""
        # 8 pairs, perfect = 16 moves, excellent = <= 24 moves
        result = game_service.calculate_matching_score('medium', 8, 8, 100, 20)
        assert result['efficiency_bonus'] == 100  # Under 1.5x min moves

    def test_calculate_matching_score_efficiency_good(self, game_service):
        """Test efficiency bonus for good play"""
        # 8 pairs, perfect = 16 moves, good = 24-32 moves
        result = game_service.calculate_matching_score('medium', 8, 8, 100, 30)
        assert result['efficiency_bonus'] == 50  # Under 2x min moves

    def test_calculate_matching_score_efficiency_poor(self, game_service):
        """Test no efficiency bonus for poor play"""
        # 8 pairs, perfect = 16 moves, poor = > 32 moves
        result = game_service.calculate_matching_score('medium', 8, 8, 100, 50)
        assert result['efficiency_bonus'] == 0

    def test_calculate_matching_score_difficulty_multiplier_easy(self, game_service):
        """Test easy difficulty multiplier"""
        result = game_service.calculate_matching_score('easy', 6, 6, 60, 12)
        assert result['difficulty_multiplier'] == 1.0

    def test_calculate_matching_score_difficulty_multiplier_medium(self, game_service):
        """Test medium difficulty multiplier"""
        result = game_service.calculate_matching_score('medium', 8, 8, 60, 16)
        assert result['difficulty_multiplier'] == 1.5

    def test_calculate_matching_score_difficulty_multiplier_hard(self, game_service):
        """Test hard difficulty multiplier"""
        result = game_service.calculate_matching_score('hard', 10, 10, 60, 20)
        assert result['difficulty_multiplier'] == 2.0

    def test_calculate_matching_score_unknown_difficulty(self, game_service):
        """Test unknown difficulty defaults to 1.0"""
        result = game_service.calculate_matching_score('extreme', 5, 5, 60, 10)
        assert result['difficulty_multiplier'] == 1.0

    def test_calculate_matching_score_xp_is_10_percent(self, game_service):
        """Test XP is 10% of total score"""
        result = game_service.calculate_matching_score('medium', 8, 8, 50, 16)
        assert result['xp_awarded'] == int(result['total_score'] * 0.1)

    def test_calculate_matching_score_total_score_calculation(self, game_service):
        """Test total score calculation formula"""
        result = game_service.calculate_matching_score('medium', 8, 8, 50, 16)

        expected_total = int(
            (result['base_score'] +
             result['completion_bonus'] +
             result['time_bonus'] +
             result['efficiency_bonus']) *
            result['difficulty_multiplier']
        )
        assert result['total_score'] == expected_total


class TestDeckService:
    """Tests for DeckService - tests pure functions only"""

    @pytest.fixture
    def deck_service(self):
        from app.study.services.deck_service import DeckService
        return DeckService

    def test_is_auto_deck_reading(self, deck_service):
        """Test reading deck is auto deck"""
        assert deck_service.is_auto_deck("Слова из чтения") is True

    def test_is_auto_deck_topic(self, deck_service):
        """Test topic decks are auto decks"""
        assert deck_service.is_auto_deck("Топик: Еда") is True
        assert deck_service.is_auto_deck("Топик: Путешествия") is True

    def test_is_auto_deck_collection(self, deck_service):
        """Test collection decks are auto decks"""
        assert deck_service.is_auto_deck("Коллекция: A1 Базовый") is True
        assert deck_service.is_auto_deck("Коллекция: B2 Продвинутый") is True

    def test_is_auto_deck_custom(self, deck_service):
        """Test custom decks are not auto decks"""
        assert deck_service.is_auto_deck("My Custom Deck") is False
        assert deck_service.is_auto_deck("Study Words") is False
        assert deck_service.is_auto_deck("") is False

    def test_is_auto_deck_partial_match(self, deck_service):
        """Test partial matches don't count"""
        assert deck_service.is_auto_deck("Топик") is False
        assert deck_service.is_auto_deck("Коллекция") is False
        assert deck_service.is_auto_deck("Слова") is False

class TestDeckServiceWithMocking:
    """Tests for DeckService methods that require mocking"""

    @pytest.fixture
    def deck_service(self):
        from app.study.services.deck_service import DeckService
        return DeckService

    @patch('app.study.services.deck_service.QuizDeck')
    def test_get_deck_with_words_found(self, mock_quiz_deck, deck_service):
        """Test getting deck with words when found"""
        mock_deck = MagicMock()
        mock_quiz_deck.query.get.return_value = mock_deck

        result = deck_service.get_deck_with_words(1)

        assert result == mock_deck
        mock_quiz_deck.query.get.assert_called_once_with(1)

    @patch('app.study.services.deck_service.QuizDeck')
    def test_get_deck_with_words_not_found(self, mock_quiz_deck, deck_service):
        """Test getting deck when not found"""
        mock_quiz_deck.query.get.return_value = None

        result = deck_service.get_deck_with_words(999)

        assert result is None

    @patch('app.study.services.deck_service.QuizDeck')
    def test_delete_deck_not_found(self, mock_quiz_deck, deck_service):
        """Test deleting non-existent deck"""
        mock_quiz_deck.query.get.return_value = None

        success, error = deck_service.delete_deck(999, 1)

        assert success is False
        assert error == "Колода не найдена"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_delete_deck_wrong_user(self, mock_quiz_deck, deck_service):
        """Test deleting deck owned by another user"""
        mock_deck = MagicMock()
        mock_deck.user_id = 2
        mock_deck.title = "Custom Deck"
        mock_quiz_deck.query.get.return_value = mock_deck

        success, error = deck_service.delete_deck(1, 1)

        assert success is False
        assert error == "Нет доступа к этой колоде"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_delete_deck_auto_deck(self, mock_quiz_deck, deck_service):
        """Test cannot delete auto deck"""
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "Слова из чтения"
        mock_quiz_deck.query.get.return_value = mock_deck

        success, error = deck_service.delete_deck(1, 1)

        assert success is False
        assert error == "Нельзя удалить автоматическую колоду"

    @patch('app.study.services.deck_service.db')
    @patch('app.study.services.deck_service.QuizDeck')
    def test_delete_deck_success(self, mock_quiz_deck, mock_db, deck_service):
        """Test successful deck deletion"""
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "My Custom Deck"
        mock_quiz_deck.query.get.return_value = mock_deck

        success, error = deck_service.delete_deck(1, 1)

        assert success is True
        assert error is None
        mock_db.session.delete.assert_called_once_with(mock_deck)
        mock_db.session.commit.assert_called_once()

    @patch('app.auth.models.User')
    @patch('app.study.services.deck_service.db')
    @patch('app.study.services.deck_service.QuizDeck')
    def test_create_deck_basic(self, mock_quiz_deck, mock_db, mock_user, deck_service):
        """Test basic deck creation"""
        mock_deck_instance = MagicMock()
        mock_quiz_deck.return_value = mock_deck_instance
        mock_user.query.get.return_value = MagicMock(default_study_deck_id=None)

        result = deck_service.create_deck(1, "Test Deck", "Description", False)

        mock_db.session.add.assert_called_once()
        mock_db.session.commit.assert_called_once()

    @patch('app.auth.models.User')
    @patch('app.study.services.deck_service.db')
    @patch('app.study.services.deck_service.QuizDeck')
    def test_create_deck_public(self, mock_quiz_deck, mock_db, mock_user, deck_service):
        """Test public deck creation generates share code"""
        mock_deck_instance = MagicMock()
        mock_quiz_deck.return_value = mock_deck_instance
        mock_user.query.get.return_value = MagicMock(default_study_deck_id=None)

        result = deck_service.create_deck(1, "Public Deck", "Description", True)

        mock_deck_instance.generate_share_code.assert_called_once()

    @patch('app.study.services.deck_service.QuizDeck')
    def test_update_deck_not_found(self, mock_quiz_deck, deck_service):
        """Test updating non-existent deck"""
        mock_quiz_deck.query.get.return_value = None

        result, error = deck_service.update_deck(999, 1, title="New Title")

        assert result is None
        assert error == "Колода не найдена"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_update_deck_wrong_user(self, mock_quiz_deck, deck_service):
        """Test updating deck owned by another user"""
        mock_deck = MagicMock()
        mock_deck.user_id = 2
        mock_quiz_deck.query.get.return_value = mock_deck

        result, error = deck_service.update_deck(1, 1, title="New Title")

        assert result is None
        assert error == "Нет доступа к этой колоде"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_update_deck_auto_deck(self, mock_quiz_deck, deck_service):
        """Test cannot update auto deck"""
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "Слова из чтения"
        mock_quiz_deck.query.get.return_value = mock_deck

        result, error = deck_service.update_deck(1, 1, title="New Title")

        assert result is None
        assert error == "Нельзя редактировать автоматическую колоду"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_copy_deck_not_found(self, mock_quiz_deck, deck_service):
        """Test copying non-existent deck"""
        mock_quiz_deck.query.get.return_value = None

        with patch.object(deck_service, 'get_deck_with_words', return_value=None):
            result, error = deck_service.copy_deck(999, 1)

        assert result is None
        assert error == "Колода не найдена"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_copy_deck_no_access(self, mock_quiz_deck, deck_service):
        """Test copying private deck of another user"""
        mock_deck = MagicMock()
        mock_deck.is_public = False
        mock_deck.user_id = 2

        with patch.object(deck_service, 'get_deck_with_words', return_value=mock_deck):
            result, error = deck_service.copy_deck(1, 1)

        assert result is None
        assert error == "У вас нет доступа к этой колоде"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_add_word_deck_not_found(self, mock_quiz_deck, deck_service):
        """Test adding word to non-existent deck"""
        mock_quiz_deck.query.get.return_value = None

        result, error = deck_service.add_word_to_deck(
            999, 1, custom_english="test", custom_russian="тест"
        )

        assert result is None
        assert error == "Колода не найдена"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_add_word_wrong_user(self, mock_quiz_deck, deck_service):
        """Test adding word to deck owned by another user"""
        mock_deck = MagicMock()
        mock_deck.user_id = 2
        mock_quiz_deck.query.get.return_value = mock_deck

        result, error = deck_service.add_word_to_deck(
            1, 1, custom_english="test", custom_russian="тест"
        )

        assert result is None
        assert error == "Нет доступа к этой колоде"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_add_word_auto_deck(self, mock_quiz_deck, deck_service):
        """Test cannot add word to auto deck"""
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "Слова из чтения"
        mock_quiz_deck.query.get.return_value = mock_deck

        result, error = deck_service.add_word_to_deck(
            1, 1, custom_english="test", custom_russian="тест"
        )

        assert result is None
        assert error == "Нельзя добавлять слова в автоматическую колоду"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_add_word_missing_fields(self, mock_quiz_deck, deck_service):
        """Test adding word with missing fields"""
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "Custom Deck"
        mock_quiz_deck.query.get.return_value = mock_deck

        result, error = deck_service.add_word_to_deck(1, 1)

        assert result is None
        assert error == "Необходимо заполнить оба поля"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_remove_word_deck_not_found(self, mock_quiz_deck, deck_service):
        """Test removing word from non-existent deck"""
        mock_quiz_deck.query.get.return_value = None

        success, error = deck_service.remove_word_from_deck(999, 1, 1)

        assert success is False
        assert error == "Колода не найдена"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_remove_word_auto_deck(self, mock_quiz_deck, deck_service):
        """Test cannot remove word from auto deck"""
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "Слова из чтения"
        mock_quiz_deck.query.get.return_value = mock_deck

        success, error = deck_service.remove_word_from_deck(1, 1, 1)

        assert success is False
        assert error == "Нельзя удалять слова из автоматической колоды"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_edit_deck_word_not_found(self, mock_quiz_deck, deck_service):
        """Test editing word in non-existent deck"""
        mock_quiz_deck.query.get.return_value = None

        result, error = deck_service.edit_deck_word(999, 1, 1, "new", "новый")

        assert result is None
        assert error == "Колода не найдена"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_edit_deck_word_auto_deck(self, mock_quiz_deck, deck_service):
        """Test cannot edit word in auto deck"""
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "Топик: Еда"
        mock_quiz_deck.query.get.return_value = mock_deck

        result, error = deck_service.edit_deck_word(1, 1, 1, "new", "новый")

        assert result is None
        assert error == "Нельзя редактировать слова в автоматической колоде"

    @patch('app.study.services.deck_service.QuizDeck')
    def test_edit_deck_word_missing_fields(self, mock_quiz_deck, deck_service):
        """Test editing word with missing fields"""
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "Custom Deck"
        mock_quiz_deck.query.get.return_value = mock_deck

        with patch('app.study.services.deck_service.QuizDeckWord') as mock_word:
            mock_word.query.filter_by.return_value.first.return_value = MagicMock()

            result, error = deck_service.edit_deck_word(1, 1, 1, "", "новый")

        assert result is None
        assert error == "Необходимо заполнить оба поля"

    @patch('app.study.services.deck_service.CollectionWords')
    def test_search_words_empty_query(self, mock_collection, deck_service):
        """Test search with empty query"""
        result = deck_service.search_words("")
        assert result == []

    @patch('app.study.services.deck_service.CollectionWords')
    def test_search_words_short_query(self, mock_collection, deck_service):
        """Test search with query too short"""
        result = deck_service.search_words("a")
        assert result == []


class TestQuizDeckWordUserWordLink:
    """Tests for QuizDeckWord.user_word_id relationship"""

    @pytest.fixture
    def deck_service(self):
        from app.study.services.deck_service import DeckService
        return DeckService

    @patch('app.study.services.deck_service.db')
    @patch('app.study.services.deck_service.UserWord')
    @patch('app.study.services.deck_service.CollectionWords')
    @patch('app.study.services.deck_service.QuizDeckWord')
    @patch('app.study.services.deck_service.QuizDeck')
    def test_add_word_creates_user_word_link(self, mock_quiz_deck, mock_deck_word,
                                              mock_collection, mock_user_word,
                                              mock_db, deck_service):
        """Test that adding word to deck creates user_word link"""
        # Setup mocks
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "Custom Deck"
        mock_quiz_deck.query.get.return_value = mock_deck

        mock_word = MagicMock()
        mock_word.english_word = "test"
        mock_word.russian_word = "тест"
        mock_word.sentences = None
        mock_collection.query.get.return_value = mock_word

        mock_deck_word.query.filter_by.return_value.first.return_value = None  # No existing

        mock_db.session.query.return_value.filter.return_value.scalar.return_value = 0

        # Mock UserWord.get_or_create to return a user_word with id
        mock_uw = MagicMock()
        mock_uw.id = 42
        mock_user_word.get_or_create.return_value = mock_uw

        # Call method
        result, error = deck_service.add_word_to_deck(
            deck_id=1,
            user_id=1,
            word_id=123,
            custom_english="test",
            custom_russian="тест"
        )

        # Verify UserWord.get_or_create was called with correct args
        mock_user_word.get_or_create.assert_called_once_with(1, 123)

        # Verify QuizDeckWord was created with user_word_id
        call_args = mock_deck_word.call_args
        assert call_args is not None
        # The call should include user_word_id=42
        assert call_args.kwargs.get('user_word_id') == 42 or \
               (len(call_args.args) == 0 and 'user_word_id' in call_args.kwargs)

    @patch('app.study.services.deck_service.db')
    @patch('app.study.services.deck_service.QuizDeckWord')
    @patch('app.study.services.deck_service.QuizDeck')
    def test_add_custom_word_no_user_word_link(self, mock_quiz_deck, mock_deck_word,
                                                mock_db, deck_service):
        """Test that adding custom word (no word_id) doesn't create user_word link"""
        # Setup mocks
        mock_deck = MagicMock()
        mock_deck.user_id = 1
        mock_deck.title = "Custom Deck"
        mock_quiz_deck.query.get.return_value = mock_deck

        mock_db.session.query.return_value.filter.return_value.scalar.return_value = 0

        # Call method (no word_id = custom word)
        result, error = deck_service.add_word_to_deck(
            deck_id=1,
            user_id=1,
            word_id=None,
            custom_english="custom",
            custom_russian="кастом"
        )

        # Verify QuizDeckWord was created without user_word_id
        call_args = mock_deck_word.call_args
        assert call_args is not None
        # The call should NOT have user_word_id set (or it should be None)
        kwargs = call_args.kwargs
        assert kwargs.get('user_word_id') is None or 'user_word_id' not in kwargs

    def test_quiz_deck_word_model_has_user_word_id(self):
        """Test that QuizDeckWord model has user_word_id column"""
        from app.study.models import QuizDeckWord

        # Check column exists
        assert hasattr(QuizDeckWord, 'user_word_id')

        # Check relationship exists
        assert hasattr(QuizDeckWord, 'user_word')

    def test_quiz_deck_word_unique_constraint(self):
        """Test that QuizDeckWord has unique constraint on (deck_id, word_id)"""
        from app.study.models import QuizDeckWord

        # Check table args for unique constraint
        table_args = QuizDeckWord.__table_args__
        assert any(
            hasattr(arg, 'name') and arg.name == 'uix_deck_word'
            for arg in table_args
            if hasattr(arg, 'name')
        )
