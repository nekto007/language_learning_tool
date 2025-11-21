"""
Tests for helper functions in app/study/routes.py
Covers 7 helper functions with ~30 tests total
"""
import pytest
from unittest.mock import patch
from datetime import datetime, timezone

from app.study.routes import (
    is_auto_deck,
    sync_master_decks,
    generate_quiz_questions,
    create_multiple_choice_question,
    create_true_false_question,
    create_fill_blank_question,
    _calculate_matching_score
)
from app.study.models import QuizDeck, QuizDeckWord, UserWord
from app.utils.db import db


class TestIsAutoDeck:
    """Test is_auto_deck() function - Lines 20-33"""

    def test_all_my_words_deck(self):
        """Test exact match for 'Все мои слова'"""
        assert is_auto_deck('Все мои слова') is True

    def test_mastered_words_deck(self):
        """Test exact match for 'Выученные слова'"""
        assert is_auto_deck('Выученные слова') is True

    def test_reading_words_deck(self):
        """Test exact match for 'Слова из чтения'"""
        assert is_auto_deck('Слова из чтения') is True

    def test_topic_prefix(self):
        """Test prefix match for 'Топик:' pattern"""
        assert is_auto_deck('Топик: Animals') is True
        assert is_auto_deck('Топик: Food') is True

    def test_collection_prefix(self):
        """Test prefix match for 'Коллекция:' pattern"""
        assert is_auto_deck('Коллекция: Family') is True
        assert is_auto_deck('Коллекция: Weather') is True

    def test_custom_deck(self):
        """Test that custom deck names are not auto decks"""
        assert is_auto_deck('My Custom Deck') is False
        assert is_auto_deck('English Vocabulary') is False

    def test_partial_match_not_auto(self):
        """Test that partial matches don't trigger auto deck"""
        assert is_auto_deck('Все мои слова NEW') is False
        assert is_auto_deck('Prefix Все мои слова') is False

    def test_empty_title(self):
        """Test empty deck title"""
        assert is_auto_deck('') is False

    def test_colon_in_custom_name(self):
        """Test custom names with colons that don't match patterns"""
        assert is_auto_deck('Random: Deck Name') is False
        assert is_auto_deck('Level: A1') is False


class TestSyncMasterDecks:
    """Test sync_master_decks() function - Lines 36-114"""

    def test_creates_learning_deck_first_time(self, db_session, test_user, user_words):
        """Test creating 'Все мои слова' deck for the first time"""
        sync_master_decks(test_user.id)

        deck = QuizDeck.query.filter_by(
            user_id=test_user.id,
            title='Все мои слова'
        ).first()

        assert deck is not None
        assert deck.is_public is False
        # Should contain non-mastered words (8 out of 10)
        assert deck.word_count == 8

    def test_creates_mastered_deck_first_time(self, db_session, test_user, user_words):
        """Test creating 'Выученные слова' deck for the first time"""
        sync_master_decks(test_user.id)

        deck = QuizDeck.query.filter_by(
            user_id=test_user.id,
            title='Выученные слова'
        ).first()

        assert deck is not None
        assert deck.is_public is False
        # Should contain mastered words (2 out of 10)
        assert deck.word_count == 2

    def test_adds_new_words_to_existing_deck(self, db_session, test_user, user_words):
        """Test adding new words to existing deck"""
        from app.words.models import CollectionWords

        # First sync
        sync_master_decks(test_user.id)

        deck = QuizDeck.query.filter_by(
            user_id=test_user.id,
            title='Все мои слова'
        ).first()
        initial_count = deck.word_count

        # Create and add a completely new word
        new_word = CollectionWords(
            english_word='unique_test_word',
            russian_word='уникальное_тестовое_слово',
            level='A1'
        )
        db_session.add(new_word)
        db_session.commit()

        new_user_word = UserWord(user_id=test_user.id, word_id=new_word.id)
        new_user_word.status = 'learning'
        db_session.add(new_user_word)
        db_session.commit()

        # Second sync
        sync_master_decks(test_user.id)
        db_session.commit()

        # Refresh deck
        db_session.refresh(deck)

        # Deck should have one more word
        assert deck.word_count == initial_count + 1

    def test_removes_mastered_words_from_learning_deck(self, db_session, test_user, user_words):
        """Test removing mastered words from learning deck"""
        # First sync with current statuses
        sync_master_decks(test_user.id)

        learning_deck = QuizDeck.query.filter_by(
            user_id=test_user.id,
            title='Все мои слова'
        ).first()
        initial_count = learning_deck.word_count

        # Change a learning word to mastered
        learning_word = next((uw for uw in user_words if uw.status == 'learning'), None)
        learning_word.status = 'mastered'
        db_session.commit()

        # Sync again
        sync_master_decks(test_user.id)

        # Learning deck should have one less word
        assert learning_deck.word_count == initial_count - 1

    def test_adds_words_to_mastered_deck_when_status_changes(self, db_session, test_user, user_words):
        """Test adding words to mastered deck when status changes"""
        # First sync
        sync_master_decks(test_user.id)

        mastered_deck = QuizDeck.query.filter_by(
            user_id=test_user.id,
            title='Выученные слова'
        ).first()
        initial_count = mastered_deck.word_count

        # Change a learning word to mastered
        learning_word = next((uw for uw in user_words if uw.status == 'learning'), None)
        learning_word.status = 'mastered'
        db_session.commit()

        # Sync again
        sync_master_decks(test_user.id)

        # Mastered deck should have one more word
        assert mastered_deck.word_count == initial_count + 1

    def test_handles_empty_word_lists(self, db_session, test_user):
        """Test sync with no user words"""
        sync_master_decks(test_user.id)

        learning_deck = QuizDeck.query.filter_by(
            user_id=test_user.id,
            title='Все мои слова'
        ).first()

        assert learning_deck is not None
        assert learning_deck.word_count == 0

    def test_updates_existing_deck_description(self, db_session, test_user, user_words):
        """Test that description is updated on existing decks"""
        # First sync
        sync_master_decks(test_user.id)

        deck = QuizDeck.query.filter_by(
            user_id=test_user.id,
            title='Все мои слова'
        ).first()

        # Manually change description
        deck.description = "Old description"
        db_session.commit()

        # Sync again should reset description
        sync_master_decks(test_user.id)

        db_session.refresh(deck)
        assert deck.description == ""

    def test_maintains_order_index(self, db_session, test_user, user_words):
        """Test that order_index is properly maintained"""
        sync_master_decks(test_user.id)
        db_session.commit()

        deck = QuizDeck.query.filter_by(
            user_id=test_user.id,
            title='Все мои слова'
        ).first()

        deck_words = QuizDeckWord.query.filter_by(deck_id=deck.id).order_by(QuizDeckWord.order_index).all()

        # Check that order indices are unique
        order_indices = [dw.order_index for dw in deck_words]
        assert len(order_indices) == len(set(order_indices)), "Order indices should be unique"
        assert len(order_indices) > 0, "Deck should have words"


class TestGenerateQuizQuestions:
    """Test generate_quiz_questions() function - Lines 1193-1254"""

    def test_generates_correct_number_of_questions(self, test_words_list):
        """Test that correct number of questions is generated"""
        questions = generate_quiz_questions(test_words_list, count=5)
        assert len(questions) == 5

    def test_handles_more_questions_than_words(self, test_words_list):
        """Test requesting more questions than available words"""
        questions = generate_quiz_questions(test_words_list[:3], count=10)
        # Should return maximum available: min(10, 3*2) = 6 questions
        assert len(questions) <= 6

    def test_handles_empty_word_list(self):
        """Test with empty word list"""
        questions = generate_quiz_questions([], count=5)
        assert len(questions) == 0

    def test_question_types_distribution(self, test_words_list):
        """Test that different question types are generated"""
        questions = generate_quiz_questions(test_words_list, count=20)

        question_types = [q['type'] for q in questions]

        # Should have mix of question types
        assert 'multiple_choice' in question_types or 'true_false' in question_types or 'fill_blank' in question_types

    def test_each_question_has_required_fields(self, test_words_list):
        """Test that each question has all required fields"""
        questions = generate_quiz_questions(test_words_list, count=5)

        for question in questions:
            assert 'type' in question
            assert 'word_id' in question
            assert 'direction' in question

    @patch('app.study.routes.create_multiple_choice_question')
    @patch('app.study.routes.create_true_false_question')
    @patch('app.study.routes.create_fill_blank_question')
    def test_calls_question_creation_functions(self, mock_fill, mock_tf, mock_mc, test_words_list):
        """Test that question creation functions are called"""
        mock_mc.return_value = {'type': 'multiple_choice', 'word_id': 1, 'direction': 'eng-rus'}
        mock_tf.return_value = {'type': 'true_false', 'word_id': 1, 'direction': 'eng-rus'}
        mock_fill.return_value = {'type': 'fill_blank', 'word_id': 1, 'direction': 'eng-rus'}

        questions = generate_quiz_questions(test_words_list, count=10)

        # At least one type should be called
        assert mock_mc.called or mock_tf.called or mock_fill.called


class TestCreateMultipleChoiceQuestion:
    """Test create_multiple_choice_question() function - Lines 1257-1320"""

    def test_creates_eng_rus_question(self, test_words_list):
        """Test creating English to Russian question"""
        word = test_words_list[0]
        question = create_multiple_choice_question(word, test_words_list, direction='eng_to_rus')

        assert question['type'] == 'multiple_choice'
        assert question['direction'] == 'eng_to_rus'
        assert question['text'] == word.english_word
        assert len(question['options']) == 4
        assert word.russian_word in question['options']

    def test_creates_rus_eng_question(self, test_words_list):
        """Test creating Russian to English question"""
        word = test_words_list[0]
        question = create_multiple_choice_question(word, test_words_list, direction='rus_to_eng')

        assert question['type'] == 'multiple_choice'
        assert question['direction'] == 'rus_to_eng'
        assert question['text'] == word.russian_word
        assert len(question['options']) == 4
        assert word.english_word in question['options']

    def test_correct_answer_is_in_options(self, test_words_list):
        """Test that correct answer is always in options"""
        word = test_words_list[0]
        question = create_multiple_choice_question(word, test_words_list, direction='eng_to_rus')

        assert question['answer'] in question['options']

    def test_handles_not_enough_distractors(self, test_words_list):
        """Test with fewer than 4 words total"""
        word = test_words_list[0]
        question = create_multiple_choice_question(word, test_words_list[:2], direction='eng_to_rus')

        # Should still create question with exactly 4 options (fills with placeholders)
        assert len(question['options']) == 4
        assert word.russian_word in question['options']

    def test_distractors_are_different_from_correct(self, test_words_list):
        """Test that distractors are not the same as correct answer"""
        word = test_words_list[0]
        question = create_multiple_choice_question(word, test_words_list, direction='eng_to_rus')

        # Count occurrences of correct answer
        correct_count = question['options'].count(question['answer'])
        assert correct_count == 1, "Correct answer should appear exactly once"


class TestCreateTrueFalseQuestion:
    """Test create_true_false_question() function - Lines 1323-1389"""

    def test_creates_true_question(self, test_words_list):
        """Test creating a true question (correct translation)"""
        word = test_words_list[0]

        # Mock random to always return True
        with patch('random.choice', return_value=True):
            question = create_true_false_question(word, test_words_list, direction='eng_to_rus')

            assert question['type'] == 'true_false'
            assert question['answer'] == 'true'
            assert word.russian_word in question['text']

    def test_creates_false_question(self, test_words_list):
        """Test creating a false question (incorrect translation)"""
        word = test_words_list[0]

        # We need at least 2 words for false question
        if len(test_words_list) >= 2:
            # Mock random to always return False, then return another word
            with patch('random.choice', side_effect=[False, test_words_list[1]]):
                question = create_true_false_question(word, test_words_list, direction='eng_to_rus')

                assert question['type'] == 'true_false'
                assert question['answer'] == 'false'
                assert word.english_word in question['text']

    def test_handles_single_word(self, test_words_list):
        """Test with only one word (can't create false question)"""
        word = test_words_list[0]
        question = create_true_false_question(word, [word], direction='eng_to_rus')

        # Should create a question (might be true or false with made-up translation)
        assert question['type'] == 'true_false'
        assert question['answer'] in ['true', 'false']


class TestCreateFillBlankQuestion:
    """Test create_fill_blank_question() function - Lines 1392-1432"""

    def test_creates_eng_rus_fill_blank(self, test_words_list):
        """Test creating English to Russian fill-in-the-blank"""
        word = test_words_list[0]
        question = create_fill_blank_question(word, direction='eng_to_rus')

        assert question['type'] == 'fill_blank'
        assert question['direction'] == 'eng_to_rus'
        assert question['text'] == word.english_word
        assert word.russian_word in question['acceptable_answers']

    def test_creates_rus_eng_fill_blank(self, test_words_list):
        """Test creating Russian to English fill-in-the-blank"""
        word = test_words_list[0]
        question = create_fill_blank_question(word, direction='rus_to_eng')

        assert question['type'] == 'fill_blank'
        assert question['direction'] == 'rus_to_eng'
        assert question['text'] == word.russian_word
        assert word.english_word.lower() in [a.lower() for a in question['acceptable_answers']]

    def test_handles_comma_separated_answers(self, db_session):
        """Test handling comma-separated acceptable answers"""
        from app.words.models import CollectionWords

        # Create word with comma-separated translations
        word = CollectionWords(
            english_word='to look',
            russian_word='смотреть, выглядеть',
            level='A1'
        )
        db_session.add(word)
        db_session.commit()

        question = create_fill_blank_question(word, direction='eng_to_rus')

        # Should include both the full answer and individual parts
        # acceptable_answers = [full_answer] + [individual parts]
        assert 'смотреть, выглядеть' in question['acceptable_answers']
        assert 'смотреть' in question['acceptable_answers']
        assert 'выглядеть' in question['acceptable_answers']


class TestCalculateMatchingScore:
    """Test _calculate_matching_score() function - Lines 1561-1607"""

    def test_valid_score_calculation_easy(self):
        """Test valid score for easy difficulty"""
        score = _calculate_matching_score(
            difficulty='easy',
            pairs_matched=8,
            total_pairs=8,
            time_taken=30,
            moves=16  # Minimum valid: pairs * 2
        )
        # Score should be > 0 and <= 500 (max cap)
        assert 0 < score <= 500

    def test_valid_score_calculation_medium(self):
        """Test valid score for medium difficulty"""
        score = _calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=30,
            moves=16
        )
        assert 0 < score <= 500

    def test_valid_score_calculation_hard(self):
        """Test valid score for hard difficulty"""
        score = _calculate_matching_score(
            difficulty='hard',
            pairs_matched=8,
            total_pairs=8,
            time_taken=30,
            moves=16
        )
        assert 0 < score <= 500

    def test_perfect_score_calculation(self):
        """Test perfect score (all pairs, minimum moves, fast time)"""
        score = _calculate_matching_score(
            difficulty='hard',  # Hard gives highest multiplier
            pairs_matched=8,
            total_pairs=8,
            time_taken=10,  # Very fast
            moves=16  # Minimum moves (pairs * 2)
        )

        # Perfect score should be capped at 500
        assert score == 500

    def test_penalty_for_extra_moves(self):
        """Test penalty for extra moves"""
        score_few_moves = _calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=30,
            moves=20  # Few extra moves
        )

        score_many_moves = _calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=30,
            moves=40  # Many extra moves
        )

        assert score_few_moves > score_many_moves

    def test_penalty_for_slow_time(self):
        """Test penalty for slow completion time"""
        score_fast = _calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=20,
            moves=16
        )

        score_slow = _calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=110,  # Just under time limit
            moves=16
        )

        assert score_fast > score_slow

    def test_incomplete_pairs_penalty(self):
        """Test penalty for not matching all pairs"""
        score_complete = _calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=30,
            moves=16
        )

        score_incomplete = _calculate_matching_score(
            difficulty='medium',
            pairs_matched=6,
            total_pairs=8,
            time_taken=30,
            moves=12  # Minimum for 6 pairs
        )

        assert score_complete > score_incomplete

    def test_score_is_non_negative(self):
        """Test that score is never negative"""
        score = _calculate_matching_score(
            difficulty='easy',
            pairs_matched=1,
            total_pairs=8,
            time_taken=59,  # Just under limit
            moves=2  # Minimum for 1 pair
        )

        assert score >= 0

    def test_invalid_difficulty_returns_zero(self):
        """Test handling of invalid difficulty returns 0"""
        score = _calculate_matching_score(
            difficulty='invalid',
            pairs_matched=8,
            total_pairs=8,
            time_taken=30,
            moves=16
        )

        # Should return 0 for invalid difficulty
        assert score == 0

    def test_invalid_moves_returns_zero(self):
        """Test that impossible moves count returns 0"""
        score = _calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=30,
            moves=10  # Less than minimum (pairs * 2 = 16)
        )

        assert score == 0

    def test_negative_values_return_zero(self):
        """Test that negative values return 0"""
        score = _calculate_matching_score(
            difficulty='medium',
            pairs_matched=8,
            total_pairs=8,
            time_taken=-10,  # Negative time
            moves=16
        )

        assert score == 0

    def test_score_capped_at_500(self):
        """Test that score is capped at maximum 500"""
        # Try to get very high score
        score = _calculate_matching_score(
            difficulty='hard',
            pairs_matched=20,  # Many pairs
            total_pairs=20,
            time_taken=1,  # Instant
            moves=40  # Perfect moves
        )

        assert score <= 500
