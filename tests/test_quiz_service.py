"""
Comprehensive tests for QuizService (app/study/services/quiz_service.py)

Tests quiz generation and scoring:
- generate_quiz_questions (multiple_choice, true_false, fill_blank)
- calculate_quiz_score
- Question type generation methods

Coverage target: 90%+ for app/study/services/quiz_service.py
"""
import pytest


class TestGenerateQuizQuestions:
    """Test generate_quiz_questions method"""

    def test_generates_requested_number_of_questions(self, test_words_list):
        """Test generates correct number of questions"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list, count=5)

        assert len(questions) == 5

    def test_handles_count_exceeding_words(self, test_words_list):
        """Test handles count larger than available words"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list[:3], count=10)

        # Should return only 3 questions (available words)
        assert len(questions) == 3

    def test_returns_empty_for_zero_count(self, test_words_list):
        """Test returns empty list for zero count"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list, count=0)

        assert questions == []

    def test_returns_empty_for_empty_words(self):
        """Test returns empty list for empty words list"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions([], count=5)

        assert questions == []

    def test_supports_specific_question_types(self, test_words_list):
        """Test supports filtering by question types"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(
            test_words_list,
            count=5,
            question_types=['multiple_choice']
        )

        assert len(questions) == 5
        assert all(q['type'] == 'multiple_choice' for q in questions)

    def test_uses_all_types_by_default(self, test_words_list):
        """Test uses all question types when not specified"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list, count=15)

        types_used = {q['type'] for q in questions}
        # With 15 questions, should use multiple types
        assert len(types_used) > 1

    def test_each_question_has_word_id(self, test_words_list):
        """Test each question includes word_id"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list, count=5)

        for q in questions:
            assert 'word_id' in q
            assert isinstance(q['word_id'], int)

    def test_does_not_repeat_words(self, test_words_list):
        """Test doesn't use same word twice"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list, count=10)

        word_ids = [q['word_id'] for q in questions]
        assert len(word_ids) == len(set(word_ids))  # All unique


class TestGenerateMultipleChoice:
    """Test _generate_multiple_choice method"""

    def test_generates_multiple_choice_question(self, test_words_list):
        """Test generates multiple choice question"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_multiple_choice(word, test_words_list)

        assert question['type'] == 'multiple_choice'
        assert question['word_id'] == word.id
        assert 'question' in question
        assert 'options' in question
        assert 'correct_answer' in question

    def test_forward_direction_english_to_russian(self, test_words_list):
        """Test forward direction (English -> Russian)"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_multiple_choice(word, test_words_list, direction='forward')

        assert question['question'] == word.english_word
        assert question['correct_answer'] == word.russian_word
        assert question['direction'] == 'forward'

    def test_reverse_direction_russian_to_english(self, test_words_list):
        """Test reverse direction (Russian -> English)"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_multiple_choice(word, test_words_list, direction='reverse')

        assert question['question'] == word.russian_word
        assert question['correct_answer'] == word.english_word
        assert question['direction'] == 'reverse'

    def test_includes_correct_answer_in_options(self, test_words_list):
        """Test correct answer is in options"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_multiple_choice(word, test_words_list)

        assert question['correct_answer'] in question['options']

    def test_generates_multiple_options(self, test_words_list):
        """Test generates multiple answer options"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_multiple_choice(word, test_words_list)

        # Should have correct answer + up to 3 wrong answers
        assert len(question['options']) >= 2
        assert len(question['options']) <= 4

    def test_shuffles_options(self, test_words_list):
        """Test options are shuffled (not always in same position)"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]

        # Generate multiple times and check if answer position varies
        positions = []
        for _ in range(10):
            q = QuizService._generate_multiple_choice(word, test_words_list)
            pos = q['options'].index(q['correct_answer'])
            positions.append(pos)

        # Should not always be in same position (statistical test)
        assert len(set(positions)) > 1


class TestGenerateTrueFalse:
    """Test _generate_true_false method"""

    def test_generates_true_false_question(self, test_words_list):
        """Test generates true/false question"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_true_false(word, test_words_list)

        assert question['type'] == 'true_false'
        assert question['word_id'] == word.id
        assert 'question' in question
        assert 'translation' in question
        assert 'correct_answer' in question
        assert isinstance(question['correct_answer'], bool)

    def test_forward_direction(self, test_words_list):
        """Test forward direction"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_true_false(word, test_words_list, direction='forward')

        assert question['question'] == word.english_word
        assert question['direction'] == 'forward'

    def test_reverse_direction(self, test_words_list):
        """Test reverse direction"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_true_false(word, test_words_list, direction='reverse')

        assert question['question'] == word.russian_word
        assert question['direction'] == 'reverse'

    def test_when_true_uses_correct_translation(self, test_words_list):
        """Test when answer is True, uses correct translation"""
        from app.study.services.quiz_service import QuizService
        import random

        word = test_words_list[0]

        # Force True by patching random
        with pytest.MonkeyPatch.context() as m:
            m.setattr(random, 'choice', lambda x: True if isinstance(x[0], bool) else x[0])

            question = QuizService._generate_true_false(word, test_words_list, direction='forward')

            if question['correct_answer']:  # If it's True
                assert question['translation'] == word.russian_word

    def test_handles_single_word_list(self, test_words_list):
        """Test handles case with only one word"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_true_false(word, [word])

        # Should force True since no wrong words available
        assert question['correct_answer'] is True
        assert question['translation'] == word.russian_word


class TestGenerateFillBlank:
    """Test _generate_fill_blank method"""

    def test_generates_fill_blank_question(self, test_words_list):
        """Test generates fill-in-blank question"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_fill_blank(word)

        assert question['type'] == 'fill_blank'
        assert question['word_id'] == word.id
        assert 'question' in question
        assert 'correct_answer' in question

    def test_forward_direction(self, test_words_list):
        """Test forward direction"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_fill_blank(word, direction='forward')

        assert word.english_word in question['question']
        assert question['correct_answer'] == word.russian_word
        assert question['direction'] == 'forward'

    def test_reverse_direction(self, test_words_list):
        """Test reverse direction"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_fill_blank(word, direction='reverse')

        assert word.russian_word in question['question']
        assert question['correct_answer'] == word.english_word
        assert question['direction'] == 'reverse'

    def test_includes_translation_prompt(self, test_words_list):
        """Test includes 'Переведите' in question"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService._generate_fill_blank(word)

        assert 'Переведите' in question['question']


class TestCalculateQuizScore:
    """Test calculate_quiz_score method"""

    def test_calculates_percentage(self):
        """Test calculates correct percentage"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=7,
            time_taken_seconds=60
        )

        assert result['percentage'] == 70.0

    def test_calculates_base_xp(self):
        """Test calculates base XP (10 per correct answer)"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=5,
            time_taken_seconds=60
        )

        assert result['xp_awarded'] >= 50  # 5 * 10

    def test_awards_perfect_score_bonus(self):
        """Test awards 50 XP bonus for perfect score"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=10,
            time_taken_seconds=60
        )

        # 10 * 10 + 50 = 150 (before time bonus)
        assert result['xp_awarded'] >= 150

    def test_no_bonus_for_imperfect_score(self):
        """Test no perfect bonus for non-perfect score"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=9,
            time_taken_seconds=120  # 12s per question - no time bonus
        )

        # 9 * 10 = 90 (no +50 bonus, no time bonus)
        assert result['xp_awarded'] == 90

    def test_very_fast_time_bonus(self):
        """Test 1.5x multiplier for very fast answers (< 5s/question)"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=5,
            time_taken_seconds=40  # 4s per question
        )

        # 5 * 10 = 50, * 1.5 = 75
        assert result['xp_awarded'] == 75

    def test_fast_time_bonus(self):
        """Test 1.2x multiplier for fast answers (< 10s/question)"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=5,
            time_taken_seconds=80  # 8s per question
        )

        # 5 * 10 = 50, * 1.2 = 60
        assert result['xp_awarded'] == 60

    def test_no_time_bonus_for_slow_answers(self):
        """Test no time bonus for slow answers (>= 10s/question)"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=5,
            time_taken_seconds=120  # 12s per question
        )

        # 5 * 10 = 50 (no multiplier)
        assert result['xp_awarded'] == 50

    def test_handles_zero_questions(self):
        """Test handles zero questions gracefully"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=0,
            correct_answers=0,
            time_taken_seconds=0
        )

        assert result['score'] == 0
        assert result['percentage'] == 0
        assert result['xp_awarded'] == 0

    def test_returns_all_required_fields(self):
        """Test returns all required fields"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=7,
            time_taken_seconds=60
        )

        required_fields = ['score', 'total', 'percentage', 'xp_awarded', 'time_taken']
        for field in required_fields:
            assert field in result

    def test_perfect_score_with_fast_time(self):
        """Test perfect score with fast time gets both bonuses"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=10,
            time_taken_seconds=40  # 4s per question
        )

        # (10 * 10 + 50) * 1.5 = 150 * 1.5 = 225
        assert result['xp_awarded'] == 225

    def test_rounds_percentage(self):
        """Test rounds percentage to 1 decimal"""
        from app.study.services.quiz_service import QuizService

        result = QuizService.calculate_quiz_score(
            total_questions=3,
            correct_answers=2,
            time_taken_seconds=30
        )

        # 2/3 = 66.666...
        assert result['percentage'] == 66.7


class TestQuizServiceIntegration:
    """Integration tests for QuizService"""

    def test_full_quiz_generation_and_scoring(self, test_words_list):
        """Test complete quiz workflow"""
        from app.study.services.quiz_service import QuizService

        # Generate quiz
        questions = QuizService.generate_quiz_questions(test_words_list, count=10)

        assert len(questions) == 10

        # Simulate answering (7 correct)
        score_result = QuizService.calculate_quiz_score(
            total_questions=10,
            correct_answers=7,
            time_taken_seconds=80
        )

        assert score_result['percentage'] == 70.0
        assert score_result['xp_awarded'] > 0

    def test_question_types_constant(self):
        """Test QUESTION_TYPES constant is defined"""
        from app.study.services.quiz_service import QuizService

        assert hasattr(QuizService, 'QUESTION_TYPES')
        assert 'multiple_choice' in QuizService.QUESTION_TYPES
        assert 'true_false' in QuizService.QUESTION_TYPES
        assert 'fill_blank' in QuizService.QUESTION_TYPES
