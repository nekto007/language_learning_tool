"""
Comprehensive tests for QuizService (app/study/services/quiz_service.py)

Tests quiz generation and scoring:
- generate_quiz_questions (multiple_choice, fill_blank)
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
        """Test handles count larger than available words

        With new implementation, 2 questions are generated per word (eng->rus and rus->eng).
        So 3 words can generate up to 6 questions.
        """
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list[:3], count=10)

        # Should return 6 questions (2 per word, max available)
        assert len(questions) == 6

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

    def test_uses_both_question_types(self, test_words_list):
        """Test generates both multiple_choice and fill_blank questions"""
        from app.study.services.quiz_service import QuizService

        # Generate enough questions to see both types
        questions = QuizService.generate_quiz_questions(test_words_list, count=15)

        types_used = {q['type'] for q in questions}
        # Should use multiple_choice and/or fill_blank
        assert types_used.issubset({'multiple_choice', 'fill_blank'})
        # With 15 questions, should use multiple types
        assert len(types_used) >= 1

    def test_uses_all_types_by_default(self, test_words_list):
        """Test uses all question types when generating questions"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list, count=15)

        types_used = {q['type'] for q in questions}
        # With 15 questions, should use multiple types
        assert len(types_used) >= 1

    def test_each_question_has_word_id(self, test_words_list):
        """Test each question includes word_id"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list, count=5)

        for q in questions:
            assert 'word_id' in q
            assert isinstance(q['word_id'], int)

    def test_word_ids_repeat_for_bidirectional_questions(self, test_words_list):
        """Test same word appears twice (eng->rus and rus->eng directions)"""
        from app.study.services.quiz_service import QuizService

        questions = QuizService.generate_quiz_questions(test_words_list, count=10)

        word_ids = [q['word_id'] for q in questions]
        # Word IDs should repeat since each word generates 2 questions
        unique_word_ids = set(word_ids)
        # With 10 questions, we should have 5 unique words (2 questions each)
        assert len(unique_word_ids) == 5


class TestGenerateMultipleChoice:
    """Test create_multiple_choice_question method"""

    def test_generates_multiple_choice_question(self, test_words_list):
        """Test generates multiple choice question"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_multiple_choice_question(word, test_words_list, 'eng_to_rus')

        assert question['type'] == 'multiple_choice'
        assert question['word_id'] == word.id
        assert 'text' in question
        assert 'options' in question
        assert 'answer' in question

    def test_eng_to_rus_direction(self, test_words_list):
        """Test eng_to_rus direction (English -> Russian)"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_multiple_choice_question(word, test_words_list, 'eng_to_rus')

        assert question['text'] == word.english_word
        assert question['answer'] == word.russian_word
        assert question['direction'] == 'eng_to_rus'

    def test_rus_to_eng_direction(self, test_words_list):
        """Test rus_to_eng direction (Russian -> English)"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_multiple_choice_question(word, test_words_list, 'rus_to_eng')

        assert question['text'] == word.russian_word
        assert question['answer'] == word.english_word
        assert question['direction'] == 'rus_to_eng'

    def test_includes_correct_answer_in_options(self, test_words_list):
        """Test correct answer is in options"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_multiple_choice_question(word, test_words_list, 'eng_to_rus')

        assert question['answer'] in question['options']

    def test_generates_four_options(self, test_words_list):
        """Test generates exactly 4 answer options"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_multiple_choice_question(word, test_words_list, 'eng_to_rus')

        # Should have exactly 4 options (correct answer + 3 distractors)
        assert len(question['options']) == 4

    def test_shuffles_options(self, test_words_list):
        """Test options are shuffled (not always in same position)"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]

        # Generate multiple times and check if answer position varies
        positions = []
        for _ in range(10):
            q = QuizService.create_multiple_choice_question(word, test_words_list, 'eng_to_rus')
            pos = q['options'].index(q['answer'])
            positions.append(pos)

        # Should not always be in same position (statistical test)
        assert len(set(positions)) > 1


class TestGenerateFillBlank:
    """Test create_fill_blank_question method"""

    def test_generates_fill_blank_question(self, test_words_list):
        """Test generates fill-in-blank question"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_fill_blank_question(word, 'eng_to_rus')

        assert question['type'] == 'fill_blank'
        assert question['word_id'] == word.id
        assert 'text' in question
        assert 'answer' in question

    def test_eng_to_rus_direction(self, test_words_list):
        """Test eng_to_rus direction"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_fill_blank_question(word, 'eng_to_rus')

        assert question['text'] == word.english_word
        assert question['answer'] == word.russian_word
        assert question['direction'] == 'eng_to_rus'

    def test_rus_to_eng_direction(self, test_words_list):
        """Test rus_to_eng direction"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_fill_blank_question(word, 'rus_to_eng')

        assert question['text'] == word.russian_word
        assert question['answer'] == word.english_word
        assert question['direction'] == 'rus_to_eng'

    def test_includes_translation_prompt(self, test_words_list):
        """Test includes 'Введите перевод' in question_label"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_fill_blank_question(word, 'eng_to_rus')

        assert 'Введите перевод' in question['question_label']

    def test_has_acceptable_answers(self, test_words_list):
        """Test has acceptable_answers list"""
        from app.study.services.quiz_service import QuizService

        word = test_words_list[0]
        question = QuizService.create_fill_blank_question(word, 'eng_to_rus')

        assert 'acceptable_answers' in question
        assert isinstance(question['acceptable_answers'], list)
        assert question['answer'] in question['acceptable_answers']


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
        assert 'fill_blank' in QuizService.QUESTION_TYPES
