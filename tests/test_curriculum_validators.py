"""
Tests for curriculum validators
Тесты валидаторов модуля curriculum
"""
import pytest
from marshmallow import ValidationError

from app.curriculum.validators import (
    VocabularyItemSchema,
    VocabularyContentSchema,
    GrammarContentSchema,
    QuizQuestionSchema,
    QuizContentSchema,
    MatchingPairSchema,
    MatchingContentSchema,
    TextContentSchema,
    CardContentSchema,
    FinalTestContentSchema,
    LessonContentValidator,
    ImportDataSchema,
    ProgressUpdateSchema,
    SRSReviewSchema,
)


class TestVocabularyItemSchema:
    """Тесты схемы элемента словаря"""

    def test_valid_vocabulary_item_with_word(self):
        """Тест валидного элемента с полем word"""
        schema = VocabularyItemSchema()
        data = {
            'word': 'hello',
            'translation': 'привет',
            'example': 'Hello, world!'
        }
        result = schema.load(data)
        assert result['word'] == 'hello'
        assert result['translation'] == 'привет'

    def test_valid_vocabulary_item_with_front(self):
        """Тест валидного элемента с полем front"""
        schema = VocabularyItemSchema()
        data = {
            'front': 'hello',
            'back': 'привет'
        }
        result = schema.load(data)
        assert result['front'] == 'hello'
        assert result['back'] == 'привет'

    def test_valid_vocabulary_item_with_english(self):
        """Тест валидного элемента с полем english"""
        schema = VocabularyItemSchema()
        data = {
            'english': 'hello',
            'russian': 'привет',
            'pronunciation': 'həˈloʊ'
        }
        result = schema.load(data)
        assert result['english'] == 'hello'
        assert result['russian'] == 'привет'

    def test_invalid_vocabulary_item_no_required_fields(self):
        """Тест невалидного элемента без обязательных полей"""
        schema = VocabularyItemSchema()
        data = {
            'translation': 'привет'  # нет word/front/english
        }
        with pytest.raises(ValidationError):
            schema.load(data)

    def test_vocabulary_item_with_additional_fields(self):
        """Тест элемента с дополнительными полями (unknown=INCLUDE)"""
        schema = VocabularyItemSchema()
        data = {
            'word': 'hello',
            'custom_field': 'custom_value',
            'audio': '[sound:hello.mp3]'
        }
        result = schema.load(data)
        assert result['word'] == 'hello'
        assert result['custom_field'] == 'custom_value'


class TestVocabularyContentSchema:
    """Тесты схемы контента словаря"""

    def test_valid_vocabulary_content_with_words(self):
        """Тест валидного контента с полем words"""
        schema = VocabularyContentSchema()
        data = {
            'words': [
                {'word': 'hello', 'translation': 'привет'},
                {'word': 'goodbye', 'translation': 'пока'}
            ]
        }
        result = schema.load(data)
        assert len(result['words']) == 2

    def test_valid_vocabulary_content_with_vocabulary(self):
        """Тест валидного контента с legacy полем vocabulary"""
        schema = VocabularyContentSchema()
        data = {
            'vocabulary': [
                {'english': 'hello', 'russian': 'привет'}
            ]
        }
        result = schema.load(data)
        assert len(result['vocabulary']) == 1

    def test_valid_vocabulary_content_with_items(self):
        """Тест валидного контента с полем items"""
        schema = VocabularyContentSchema()
        data = {
            'items': [
                {'front': 'hello', 'back': 'привет'}
            ]
        }
        result = schema.load(data)
        assert len(result['items']) == 1

    def test_invalid_vocabulary_content_no_vocab_field(self):
        """Тест невалидного контента без словарных полей"""
        schema = VocabularyContentSchema()
        data = {
            'settings': {'some': 'setting'}
        }
        with pytest.raises(ValidationError):
            schema.load(data)

    def test_vocabulary_content_with_settings(self):
        """Тест контента с настройками"""
        schema = VocabularyContentSchema()
        data = {
            'words': [{'word': 'test', 'translation': 'тест'}],
            'settings': {
                'show_pronunciation': True,
                'auto_play_audio': False
            }
        }
        result = schema.load(data)
        assert result['settings']['show_pronunciation'] is True


class TestGrammarContentSchema:
    """Тесты схемы грамматического контента"""

    def test_valid_grammar_content_with_content(self):
        """Тест валидного грамматического контента"""
        schema = GrammarContentSchema()
        data = {
            'title': 'Present Simple',
            'content': 'Present Simple is used for...',
            'examples': ['I go to school', 'She works here']
        }
        result = schema.load(data)
        assert result['title'] == 'Present Simple'
        assert len(result['examples']) == 2

    def test_valid_grammar_content_with_rule(self):
        """Тест с полем rule"""
        schema = GrammarContentSchema()
        data = {
            'rule': 'Use -s for third person singular'
        }
        result = schema.load(data)
        assert result['rule'] == 'Use -s for third person singular'

    def test_valid_grammar_content_with_exercises(self):
        """Тест с упражнениями"""
        schema = GrammarContentSchema()
        data = {
            'content': 'Grammar explanation',
            'exercises': [
                {
                    'type': 'fill_blank',
                    'sentence': 'I ___ a student',
                    'correct': 'am'
                }
            ]
        }
        result = schema.load(data)
        assert len(result['exercises']) == 1

    def test_invalid_grammar_content_empty(self):
        """Тест невалидного пустого грамматического контента"""
        schema = GrammarContentSchema()
        data = {}
        with pytest.raises(ValidationError):
            schema.load(data)

    def test_grammar_content_with_grammar_explanation(self):
        """Тест с complex grammar explanation"""
        schema = GrammarContentSchema()
        data = {
            'grammar_explanation': {
                'rule': 'Present Simple rule',
                'usage': ['habitual actions', 'general truths'],
                'structure': 'Subject + Verb (base form)'
            }
        }
        result = schema.load(data)
        assert 'grammar_explanation' in result


class TestQuizQuestionSchema:
    """Тесты схемы вопроса квиза"""

    def test_valid_multiple_choice_question(self):
        """Тест валидного multiple choice вопроса"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'multiple_choice',
            'question': 'What is 2+2?',
            'options': ['3', '4', '5'],
            'correct': 1
        }
        result = schema.load(data)
        assert result['type'] == 'multiple_choice'
        assert len(result['options']) == 3

    def test_valid_true_false_question(self):
        """Тест валидного true/false вопроса"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'true_false',
            'question': 'The sky is blue',
            'correct': True
        }
        result = schema.load(data)
        assert result['type'] == 'true_false'

    def test_valid_translation_question(self):
        """Тест валидного translation вопроса"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'translation',
            'russian': 'Привет',
            'question': 'Translate to English',
            'correct_answer': 'Hello'
        }
        result = schema.load(data)
        assert result['type'] == 'translation'

    def test_valid_fill_blank_question(self):
        """Тест валидного fill_blank вопроса"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'fill_blank',
            'sentence': 'I ___ a student',
            'options': ['am', 'is', 'are'],
            'correct_answer': 'am'
        }
        result = schema.load(data)
        assert result['type'] == 'fill_blank'

    def test_invalid_question_type(self):
        """Тест невалидного типа вопроса"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'invalid_type',
            'question': 'Test question'
        }
        with pytest.raises(ValidationError):
            schema.load(data)

    def test_question_with_alternative_field_names(self):
        """Тест вопроса с альтернативными именами полей"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'multiple_choice',
            'prompt': 'Choose correct answer',  # вместо question
            'options': ['a', 'b', 'c']
        }
        result = schema.load(data)
        assert result['prompt'] == 'Choose correct answer'

    def test_multiple_choice_with_string_correct_not_in_options(self):
        """Тест multiple choice когда correct - строка, но не в options (нормализуется позже)"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'multiple_choice',
            'question': 'What is the capital?',
            'options': ['Paris', 'London', 'Berlin'],
            'correct': 'paris'  # lowercase, not exactly in options
        }
        # Should not raise error - will be normalized later
        result = schema.load(data)
        assert result['correct'] == 'paris'


class TestQuizContentSchema:
    """Тесты схемы контента квиза"""

    def test_valid_quiz_content(self):
        """Тест валидного контента квиза"""
        schema = QuizContentSchema()
        data = {
            'questions': [
                {
                    'type': 'multiple_choice',
                    'question': 'Q1',
                    'options': ['a', 'b'],
                    'correct': 0
                }
            ]
        }
        result = schema.load(data)
        assert len(result['questions']) == 1

    def test_quiz_content_with_multiple_questions(self):
        """Тест контента с несколькими вопросами"""
        schema = QuizContentSchema()
        data = {
            'questions': [
                {'type': 'multiple_choice', 'question': 'Q1', 'options': ['a', 'b'], 'correct': 0},
                {'type': 'true_false', 'question': 'Q2', 'correct': True},
                {'type': 'translation', 'question': 'Q3', 'russian': 'Привет', 'correct_answer': 'Hello'}
            ]
        }
        result = schema.load(data)
        assert len(result['questions']) == 3


class TestMatchingSchema:
    """Тесты схем matching заданий"""

    def test_valid_matching_pair(self):
        """Тест валидной пары для matching"""
        schema = MatchingPairSchema()
        data = {
            'left': 'hello',
            'right': 'привет'
        }
        result = schema.load(data)
        assert result['left'] == 'hello'
        assert result['right'] == 'привет'

    def test_valid_matching_content(self):
        """Тест валидного контента matching"""
        schema = MatchingContentSchema()
        data = {
            'pairs': [
                {'left': 'hello', 'right': 'привет'},
                {'left': 'goodbye', 'right': 'пока'}
            ]
        }
        result = schema.load(data)
        assert len(result['pairs']) == 2


class TestTextContentSchema:
    """Тесты схемы текстового контента"""

    def test_valid_text_content_with_text(self):
        """Тест валидного текстового контента"""
        schema = TextContentSchema()
        data = {
            'text': 'This is a sample text for reading lesson.',
            'title': 'Reading Lesson'
        }
        result = schema.load(data)
        assert result['text'] == 'This is a sample text for reading lesson.'

    def test_valid_text_content_with_content(self):
        """Тест с полем content вместо text"""
        schema = TextContentSchema()
        data = {
            'content': 'Sample content'
        }
        result = schema.load(data)
        assert result['content'] == 'Sample content'

    def test_text_content_with_questions(self):
        """Тест текстового контента с вопросами"""
        schema = TextContentSchema()
        data = {
            'text': 'Sample text',
            'questions': [
                {
                    'type': 'multiple_choice',
                    'question': 'What is the main idea?',
                    'options': ['a', 'b', 'c'],
                    'correct': 0
                }
            ]
        }
        result = schema.load(data)
        assert len(result['questions']) == 1


class TestCardContentSchema:
    """Тесты схемы контента карточек"""

    def test_valid_card_content(self):
        """Тест валидного контента карточек"""
        schema = CardContentSchema()
        data = {
            'cards': [
                {'front': 'hello', 'back': 'привет'}
            ]
        }
        result = schema.load(data)
        assert len(result['cards']) == 1


class TestFinalTestContentSchema:
    """Тесты схемы финального теста"""

    def test_valid_final_test_content(self):
        """Тест валидного контента финального теста"""
        schema = FinalTestContentSchema()
        data = {
            'questions': [
                {
                    'type': 'multiple_choice',
                    'question': 'Final test question',
                    'options': ['a', 'b', 'c'],
                    'correct': 0
                }
            ],
            'passing_score': 70
        }
        result = schema.load(data)
        assert len(result['questions']) == 1
        assert result['passing_score'] == 70


class TestLessonContentValidator:
    """Тесты валидатора контента урока"""

    def test_validate_vocabulary_lesson(self):
        """Тест валидации vocabulary урока"""
        data = {
            'words': [
                {'word': 'hello', 'translation': 'привет'}
            ]
        }
        result = LessonContentValidator.validate('vocabulary', data)
        assert result is not None

    def test_validate_grammar_lesson(self):
        """Тест валидации grammar урока"""
        data = {
            'content': 'Grammar explanation',
            'examples': ['Example 1']
        }
        result = LessonContentValidator.validate('grammar', data)
        assert result is not None

    def test_validate_quiz_lesson(self):
        """Тест валидации quiz урока"""
        data = {
            'questions': [
                {
                    'type': 'multiple_choice',
                    'question': 'Test?',
                    'options': ['a', 'b'],
                    'correct': 0
                }
            ]
        }
        result = LessonContentValidator.validate('quiz', data)
        assert result is not None

    def test_validate_matching_lesson(self):
        """Тест валидации matching урока"""
        data = {
            'pairs': [
                {'left': 'hello', 'right': 'привет'}
            ]
        }
        result = LessonContentValidator.validate('matching', data)
        assert result is not None

    def test_validate_text_lesson(self):
        """Тест валидации text урока"""
        data = {
            'text': 'Sample reading text'
        }
        result = LessonContentValidator.validate('text', data)
        assert result is not None

    def test_validate_card_lesson(self):
        """Тест валидации card урока"""
        data = {
            'cards': [
                {'front': 'hello', 'back': 'привет'}
            ]
        }
        result = LessonContentValidator.validate('card', data)
        assert result is not None

    def test_validate_final_test_lesson(self):
        """Тест валидации final_test урока"""
        data = {
            'questions': [
                {
                    'type': 'multiple_choice',
                    'question': 'Test?',
                    'options': ['a', 'b'],
                    'correct': 0
                }
            ]
        }
        result = LessonContentValidator.validate('final_test', data)
        assert result is not None

    def test_validate_invalid_lesson_type(self):
        """Тест валидации невалидного типа урока"""
        data = {}
        with pytest.raises(ValueError):
            LessonContentValidator.validate('invalid_type', data)


class TestProgressUpdateSchema:
    """Тесты схемы обновления прогресса"""

    def test_valid_progress_update(self):
        """Тест валидного обновления прогресса"""
        schema = ProgressUpdateSchema()
        data = {
            'lesson_id': 1,
            'score': 85.0,
            'status': 'completed'
        }
        result = schema.load(data)
        assert result['lesson_id'] == 1
        assert result['score'] == 85.0
        assert result['status'] == 'completed'

    def test_progress_update_with_optional_fields(self):
        """Тест обновления прогресса с опциональными полями"""
        schema = ProgressUpdateSchema()
        data = {
            'lesson_id': 1,
            'score': 90.0,
            'status': 'completed',
            'time_spent': 300,
            'attempts': 2
        }
        result = schema.load(data)
        assert result['time_spent'] == 300
        assert result['attempts'] == 2


class TestSRSReviewSchema:
    """Тесты схемы SRS review"""

    def test_valid_srs_review(self):
        """Тест валидного SRS review"""
        schema = SRSReviewSchema()
        data = {
            'word_id': 1,
            'direction': 'en_ru',
            'rating': 4
        }
        result = schema.load(data)
        assert result['word_id'] == 1
        assert result['direction'] == 'en_ru'
        assert result['rating'] == 4

    def test_srs_review_with_session_data(self):
        """Тест SRS review с данными сессии"""
        schema = SRSReviewSchema()
        data = {
            'word_id': 1,
            'direction': 'en_ru',
            'rating': 5,
            'session_id': 'abc123',
            'response_time': 2.5
        }
        result = schema.load(data)
        assert result['session_id'] == 'abc123'
        assert result['response_time'] == 2.5


class TestEdgeCasesAndErrors:
    """Тесты граничных случаев и ошибок валидации"""

    def test_vocabulary_item_empty_word(self):
        """Тест элемента словаря с пустым word"""
        schema = VocabularyItemSchema()
        data = {
            'word': '',
            'translation': 'test'
        }
        # Пустая строка считается как отсутствие поля
        with pytest.raises(ValidationError):
            schema.load(data)

    def test_quiz_question_too_long(self):
        """Тест вопроса квиза с слишком длинным текстом"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'multiple_choice',
            'question': 'x' * 501,  # max 500 символов
            'options': ['a', 'b'],
            'correct': 0
        }
        with pytest.raises(ValidationError):
            schema.load(data)

    def test_grammar_content_too_short_title(self):
        """Тест грамматического контента с пустым title"""
        schema = GrammarContentSchema()
        data = {
            'title': '',  # min 1 символ
            'content': 'Some content'
        }
        with pytest.raises(ValidationError):
            schema.load(data)

    def test_lesson_validator_with_invalid_data(self):
        """Тест валидатора урока с невалидными данными"""
        data = {
            'words': []  # пустой массив - невалидно
        }
        with pytest.raises(ValidationError):
            LessonContentValidator.validate('vocabulary', data)

    def test_multiple_validation_errors(self):
        """Тест множественных ошибок валидации"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'invalid_type',  # невалидный тип
            'question': 'x' * 501,   # слишком длинный
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        # Проверяем что есть ошибки
        assert exc_info.value.messages is not None


class TestQuizQuestionValidationErrors:
    """Тесты ошибок валидации QuizQuestionSchema"""

    def test_multiple_choice_without_question_or_prompt(self):
        """Тест multiple_choice без question/prompt"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'multiple_choice',
            'options': ['a', 'b', 'c']
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'question' in str(exc_info.value) or 'prompt' in str(exc_info.value)

    def test_multiple_choice_without_options(self):
        """Тест multiple_choice без options"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'multiple_choice',
            'question': 'Test?'
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'options' in str(exc_info.value)

    def test_multiple_choice_correct_index_out_of_range(self):
        """Тест multiple_choice с correct_index вне диапазона"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'multiple_choice',
            'question': 'Test?',
            'options': ['a', 'b'],
            'correct': 5  # индекс вне диапазона
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'out of range' in str(exc_info.value).lower()

    def test_true_false_without_correct_answer(self):
        """Тест true_false без correct_answer"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'true_false',
            'question': 'Test?'
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'correct' in str(exc_info.value).lower()

    def test_fill_blank_without_correct_answer(self):
        """Тест fill_blank без correct_answer"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'fill_in_blank',
            'instruction': 'Fill blank'
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'correct' in str(exc_info.value).lower()

    def test_reorder_without_words(self):
        """Тест reorder без words"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'reorder',
            'instruction': 'Reorder words',
            'correct_answer': 'test'
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'words' in str(exc_info.value).lower()

    def test_reorder_without_correct_answer(self):
        """Тест reorder без correct_answer"""
        schema = QuizQuestionSchema()
        data = {
            'type': 'reorder',
            'instruction': 'Reorder words',
            'words': ['a', 'b', 'c']
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'correct_answer' in str(exc_info.value).lower()


class TestQuizContentSchemaErrors:
    """Тесты ошибок QuizContentSchema"""

    def test_quiz_without_questions_or_exercises(self):
        """Тест quiz без questions и exercises"""
        schema = QuizContentSchema()
        data = {}  # Пустой словарь без questions и exercises
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'questions' in str(exc_info.value).lower() or 'exercises' in str(exc_info.value).lower()

    def test_quiz_with_exercises_normalizes_to_questions(self):
        """Тест нормализации exercises → questions"""
        schema = QuizContentSchema()
        data = {
            'exercises': [
                {
                    'type': 'multiple_choice',
                    'question': 'Test?',
                    'options': ['a', 'b'],
                    'correct': 0
                }
            ]
        }
        result = schema.load(data)
        assert 'questions' in result
        assert 'exercises' not in result
        assert len(result['questions']) == 1


class TestMatchingPairSchemaErrors:
    """Тесты ошибок MatchingPairSchema"""

    def test_pair_without_required_fields(self):
        """Тест пары без обязательных полей"""
        schema = MatchingPairSchema()
        data = {
            'hint': 'some hint'
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'left' in str(exc_info.value).lower() or 'right' in str(exc_info.value).lower()


class TestTextContentSchemaErrors:
    """Тесты ошибок TextContentSchema"""

    def test_text_without_content_or_text(self):
        """Тест text урока без content и text"""
        schema = TextContentSchema()
        data = {
            'title': 'Test'
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'content' in str(exc_info.value).lower() or 'text' in str(exc_info.value).lower()


class TestLessonContentValidatorEdgeCases:
    """Тесты edge cases LessonContentValidator"""

    def test_validate_vocabulary_with_list_content(self):
        """Тест vocabulary с list вместо dict"""
        content = [
            {'word': 'hello', 'translation': 'привет'}
        ]
        is_valid, error_msg, cleaned_data = LessonContentValidator.validate('vocabulary', content)
        assert is_valid is True
        assert cleaned_data is not None
        assert 'words' in cleaned_data


class TestImportDataSchemaErrors:
    """Тесты ошибок ImportDataSchema"""

    def test_import_without_levels(self):
        """Тест импорта без levels"""
        schema = ImportDataSchema()
        data = {
            'levels': []
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'level' in str(exc_info.value).lower()

    def test_import_level_without_code(self):
        """Тест level без code"""
        schema = ImportDataSchema()
        data = {
            'levels': [
                {
                    'name': 'A1',
                    'modules': []
                }
            ]
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'code' in str(exc_info.value).lower()

    def test_import_level_without_modules(self):
        """Тест level без modules"""
        schema = ImportDataSchema()
        data = {
            'levels': [
                {
                    'code': 'A1',
                    'name': 'Beginner'
                }
            ]
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'modules' in str(exc_info.value).lower()

    def test_import_module_without_number(self):
        """Тест module без number"""
        schema = ImportDataSchema()
        data = {
            'levels': [
                {
                    'code': 'A1',
                    'modules': [
                        {
                            'title': 'Module 1',
                            'lessons': []
                        }
                    ]
                }
            ]
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'number' in str(exc_info.value).lower()

    def test_import_module_without_lessons(self):
        """Тест module без lessons"""
        schema = ImportDataSchema()
        data = {
            'levels': [
                {
                    'code': 'A1',
                    'modules': [
                        {
                            'number': 1,
                            'title': 'Module 1'
                        }
                    ]
                }
            ]
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'lessons' in str(exc_info.value).lower()


class TestProgressUpdateSchemaErrors:
    """Тесты ошибок ProgressUpdateSchema"""

    def test_progress_completed_exceeds_total(self):
        """Тест когда completed > total"""
        schema = ProgressUpdateSchema()
        data = {
            'lesson_id': 1,
            'status': 'in_progress',
            'completed_items': 10,
            'total_items': 5
        }
        with pytest.raises(ValidationError) as exc_info:
            schema.load(data)
        assert 'exceed' in str(exc_info.value).lower()


class TestValidateRequestData:
    """Тесты функции validate_request_data"""

    def test_validate_request_data_with_errors(self):
        """Тест validate_request_data с ошибками"""
        from app.curriculum.validators import validate_request_data

        data = {
            'translation': 'привет'  # Нет обязательных полей word/front/english
        }
        is_valid, error_msg, cleaned_data = validate_request_data(VocabularyItemSchema, data)
        assert is_valid is False
        assert error_msg is not None
        assert cleaned_data is None

    def test_validate_request_data_success(self):
        """Тест validate_request_data с валидными данными"""
        from app.curriculum.validators import validate_request_data

        data = {
            'word': 'hello',
            'translation': 'привет'
        }
        is_valid, error_msg, cleaned_data = validate_request_data(VocabularyItemSchema, data)
        assert is_valid is True
        assert error_msg is None
        assert cleaned_data is not None
        assert cleaned_data['word'] == 'hello'

    def test_validate_request_data_with_dict_errors(self):
        """Тест validate_request_data когда ошибки не список, а словарь/строка"""
        from app.curriculum.validators import validate_request_data
        from marshmallow import ValidationError
        from unittest.mock import patch

        # Mock ValidationError to have non-list error messages
        data = {'word': 'test'}

        # Patch the schema.load to raise ValidationError with non-list errors
        with patch.object(VocabularyItemSchema, 'load') as mock_load:
            # Create ValidationError with dict containing non-list error (string)
            mock_load.side_effect = ValidationError({'field_name': 'This is a string error, not a list'})

            is_valid, error_msg, cleaned_data = validate_request_data(VocabularyItemSchema, data)
            assert is_valid is False
            assert error_msg is not None
            assert 'field_name' in error_msg
            assert 'This is a string error' in error_msg