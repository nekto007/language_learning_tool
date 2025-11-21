"""Tests for LessonService"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, UTC
from app.curriculum.services.lesson_service import LessonService


@pytest.fixture
def quiz_lesson():
    """Create a mock quiz lesson"""
    lesson = Mock()
    lesson.id = 1
    lesson.type = 'quiz'
    lesson.content = {
        'questions': [
            {'question': 'Q1', 'options': ['A', 'B', 'C'], 'correct': 1, 'explanation': 'B is correct'},
            {'question': 'Q2', 'options': ['X', 'Y', 'Z'], 'correct': 2},
            {'question': 'Q3', 'options': ['1', '2', '3'], 'correct': 0}
        ],
        'passing_score': 70
    }
    return lesson


@pytest.fixture
def grammar_lesson():
    """Create a mock grammar lesson"""
    lesson = Mock()
    lesson.id = 2
    lesson.type = 'grammar'
    lesson.content = {
        'exercises': [
            {'type': 'fill_blank', 'question': 'Fill in ___', 'answer': 'the'},
            {'question': 'Complete: He ___ there', 'correct_answer': 'goes'},
            {'question': 'Fill: She ___ happy', 'answer': 'is'}
        ]
    }
    return lesson


@pytest.fixture
def matching_lesson():
    """Create a mock matching lesson"""
    lesson = Mock()
    lesson.id = 3
    lesson.type = 'matching'
    lesson.content = {
        'pairs': [
            {'left': 'Apple', 'right': 'Яблоко'},
            {'left': 'Book', 'right': 'Книга'},
            {'left': 'Cat', 'right': 'Кот'}
        ]
    }
    return lesson


class TestProcessQuizSubmission:
    """Test process_quiz_submission method"""

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_perfect_score(self, mock_progress, quiz_lesson):
        """Test quiz with all correct answers"""
        answers = {0: 1, 1: 2, 2: 0}  # All correct

        result = LessonService.process_quiz_submission(quiz_lesson, 1, answers)

        assert result['success'] is True
        assert result['score'] == 100
        assert result['correct_count'] == 3
        assert result['total_count'] == 3
        assert result['completed'] is True

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_partial_score(self, mock_progress, quiz_lesson):
        """Test quiz with some correct answers"""
        answers = {0: 1, 1: 0, 2: 0}  # 2 correct out of 3

        result = LessonService.process_quiz_submission(quiz_lesson, 1, answers)

        assert result['score'] == 67  # 2/3 * 100, rounded
        assert result['correct_count'] == 2
        assert result['completed'] is False  # Below 70%

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_zero_score(self, mock_progress, quiz_lesson):
        """Test quiz with all wrong answers"""
        answers = {0: 0, 1: 0, 2: 1}  # All wrong

        result = LessonService.process_quiz_submission(quiz_lesson, 1, answers)

        assert result['score'] == 0
        assert result['correct_count'] == 0

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_feedback_includes_explanations(self, mock_progress, quiz_lesson):
        """Test that feedback includes explanations for wrong answers"""
        answers = {0: 0, 1: 2, 2: 0}  # First wrong, others correct

        result = LessonService.process_quiz_submission(quiz_lesson, 1, answers)

        # Wrong answer should have explanation
        assert result['feedback'][0]['correct'] is False
        assert 'explanation' in result['feedback'][0]
        assert result['feedback'][0]['explanation'] == 'B is correct'

        # Correct answer shouldn't have explanation (or empty)
        assert result['feedback'][1]['correct'] is True

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_progress_updated_with_answers(self, mock_progress, quiz_lesson):
        """Test that progress is updated with answers and feedback"""
        answers = {0: 1, 1: 2, 2: 0}

        result = LessonService.process_quiz_submission(quiz_lesson, 1, answers)

        # Verify progress service was called
        mock_progress.create_or_update_progress.assert_called_once()
        call_args = mock_progress.create_or_update_progress.call_args[1]

        assert call_args['user_id'] == 1
        assert call_args['lesson_id'] == 1
        assert call_args['status'] == 'completed'
        assert call_args['score'] == 100
        assert 'answers' in call_args['data']

    def test_non_quiz_lesson_raises_error(self):
        """Test that non-quiz lesson raises ValueError"""
        lesson = Mock()
        lesson.type = 'vocabulary'

        result = LessonService.process_quiz_submission(lesson, 1, {})

        assert result['success'] is False
        assert 'error' in result


class TestProcessGrammarSubmission:
    """Test process_grammar_submission method"""

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_perfect_score(self, mock_progress, grammar_lesson):
        """Test grammar with all correct answers"""
        answers = {0: 'the', 1: 'goes', 2: 'is'}

        result = LessonService.process_grammar_submission(grammar_lesson, 1, answers)

        assert result['success'] is True
        assert result['score'] == 100
        assert result['correct_count'] == 3
        assert result['completed'] is True

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_case_insensitive_matching(self, mock_progress, grammar_lesson):
        """Test that answers are case-insensitive"""
        answers = {0: 'THE', 1: 'GOES', 2: 'IS'}  # Uppercase

        result = LessonService.process_grammar_submission(grammar_lesson, 1, answers)

        assert result['score'] == 100  # Should still be correct

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_whitespace_trimmed(self, mock_progress, grammar_lesson):
        """Test that whitespace is trimmed from answers"""
        answers = {0: '  the  ', 1: ' goes', 2: 'is '}

        result = LessonService.process_grammar_submission(grammar_lesson, 1, answers)

        assert result['score'] == 100

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_partial_score(self, mock_progress, grammar_lesson):
        """Test grammar with some correct answers"""
        answers = {0: 'the', 1: 'wrong', 2: 'is'}  # 2 out of 3

        result = LessonService.process_grammar_submission(grammar_lesson, 1, answers)

        assert result['score'] == 67  # 2/3 * 100
        assert result['correct_count'] == 2

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_missing_answers_treated_as_empty(self, mock_progress, grammar_lesson):
        """Test that missing answers are treated as empty strings"""
        answers = {0: 'the'}  # Only first answer provided

        result = LessonService.process_grammar_submission(grammar_lesson, 1, answers)

        assert result['correct_count'] == 1  # Only first is correct

    def test_non_grammar_lesson_raises_error(self):
        """Test that non-grammar lesson returns error"""
        lesson = Mock()
        lesson.type = 'quiz'

        result = LessonService.process_grammar_submission(lesson, 1, {})

        assert result['success'] is False


class TestProcessMatchingSubmission:
    """Test process_matching_submission method"""

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_perfect_matching(self, mock_progress, matching_lesson):
        """Test matching with all correct pairs"""
        matches = [
            {'left_index': 0, 'right_index': 0},
            {'left_index': 1, 'right_index': 1},
            {'left_index': 2, 'right_index': 2}
        ]

        result = LessonService.process_matching_submission(matching_lesson, 1, matches)

        assert result['success'] is True
        assert result['score'] == 100
        assert result['correct_count'] == 3
        assert result['completed'] is True

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_partial_matching(self, mock_progress, matching_lesson):
        """Test matching with some correct pairs"""
        matches = [
            {'left_index': 0, 'right_index': 0},  # Correct
            {'left_index': 1, 'right_index': 2},  # Wrong
            {'left_index': 2, 'right_index': 1}   # Wrong
        ]

        result = LessonService.process_matching_submission(matching_lesson, 1, matches)

        assert result['score'] == 33  # 1/3 * 100
        assert result['correct_count'] == 1
        assert result['completed'] is False  # Below 80%

    @patch('app.curriculum.services.progress_service.ProgressService')
    def test_incomplete_matches(self, mock_progress, matching_lesson):
        """Test with incomplete matches"""
        matches = [
            {'left_index': 0, 'right_index': 0}  # Only one match
        ]

        result = LessonService.process_matching_submission(matching_lesson, 1, matches)

        assert result['correct_count'] == 1
        assert result['total_count'] == 3

    def test_non_matching_lesson_raises_error(self):
        """Test that non-matching lesson returns error"""
        lesson = Mock()
        lesson.type = 'quiz'

        result = LessonService.process_matching_submission(lesson, 1, [])

        assert result['success'] is False


class TestGetVocabularyWords:
    """Test get_vocabulary_words method"""

    @patch('app.curriculum.services.lesson_service.CollectionWords')
    @patch('app.curriculum.services.lesson_service.UserWord')
    def test_gets_vocabulary_from_dict_content(self, mock_user_word, mock_collection):
        """Test getting vocabulary from dictionary content structure"""
        lesson = Mock()
        lesson.type = 'vocabulary'
        lesson.content = {
            'words': [
                {'word': 'apple', 'translation': 'яблоко', 'example': 'I eat an apple'},
                {'word': 'book', 'translation': 'книга'}
            ]
        }

        word1 = Mock(id=1, english_word='apple', russian_word='яблоко', level='A1', audio_url=None)
        word2 = Mock(id=2, english_word='book', russian_word='книга', level='A1', audio_url=None)

        mock_collection.query.filter_by.return_value.first.side_effect = [word1, word2]
        mock_user_word.query.filter_by.return_value.first.return_value = None

        result = LessonService.get_vocabulary_words(lesson, 1)

        assert len(result) == 2
        assert result[0]['english'] == 'apple'
        assert result[0]['russian'] == 'яблоко'
        assert result[0]['status'] == 'new'

    @patch('app.curriculum.services.lesson_service.CollectionWords')
    @patch('app.curriculum.services.lesson_service.UserWord')
    def test_handles_user_word_status(self, mock_user_word, mock_collection):
        """Test that user word status is included"""
        lesson = Mock()
        lesson.content = {'words': [{'word': 'test'}]}

        word = Mock(id=1, english_word='test', russian_word='тест', level='A1')
        user_word = Mock(status='learning')

        mock_collection.query.filter_by.return_value.first.return_value = word
        mock_user_word.query.filter_by.return_value.first.return_value = user_word

        result = LessonService.get_vocabulary_words(lesson, 1)

        assert result[0]['status'] == 'learning'

    def test_handles_exception_gracefully(self):
        """Test that exceptions are handled"""
        lesson = Mock()
        lesson.content = None  # Will cause error

        result = LessonService.get_vocabulary_words(lesson, 1)

        assert result == []


class TestProcessFinalTestSubmission:
    """Test process_final_test_submission method"""

    @patch('app.curriculum.services.progress_service.ProgressService')
    @patch.object(LessonService, '_process_quiz_section')
    @patch.object(LessonService, '_process_grammar_section')
    def test_combined_sections(self, mock_grammar, mock_quiz, mock_progress):
        """Test final test with multiple sections"""
        lesson = Mock()
        lesson.id = 1
        lesson.type = 'final_test'
        lesson.content = {
            'quiz_questions': [],
            'grammar_exercises': [],
            'passing_score': 70
        }

        mock_quiz.return_value = {'score': 80, 'weight': 1.0}
        mock_grammar.return_value = {'score': 90, 'weight': 1.0}

        data = {
            'quiz_answers': {},
            'grammar_answers': {}
        }

        result = LessonService.process_final_test_submission(lesson, 1, data)

        assert result['success'] is True
        assert result['score'] == 85  # (80 * 1.0 + 90 * 1.0) / 2
        assert result['completed'] is True


class TestHelperMethods:
    """Test helper methods"""

    def test_process_quiz_section(self):
        """Test _process_quiz_section helper"""
        questions = [
            {'question': 'Q1', 'correct': 0},
            {'question': 'Q2', 'correct': 1}
        ]
        answers = {0: 0, 1: 1}  # Both correct

        result = LessonService._process_quiz_section(questions, answers)

        assert result['score'] == 100
        assert result['correct_count'] == 2

    def test_process_grammar_section(self):
        """Test _process_grammar_section helper"""
        exercises = [
            {'answer': 'the'},
            {'answer': 'is'}
        ]
        answers = {0: 'the', 1: 'was'}  # One correct

        result = LessonService._process_grammar_section(exercises, answers)

        assert result['score'] == 50
        assert result['correct_count'] == 1