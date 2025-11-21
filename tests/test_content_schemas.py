"""
Tests for content schemas
Тесты схем контента уроков
"""
import pytest
from app.curriculum.content_schemas import LessonType, StandardContentSchemas


class TestLessonType:
    """Тесты enum типов уроков"""

    def test_lesson_type_values(self):
        """Тест значений enum"""
        assert LessonType.VOCABULARY.value == "vocabulary"
        assert LessonType.GRAMMAR.value == "grammar"
        assert LessonType.QUIZ.value == "quiz"
        assert LessonType.MATCHING.value == "matching"
        assert LessonType.TEXT.value == "text"
        assert LessonType.CARD.value == "card"
        assert LessonType.FINAL_TEST.value == "final_test"


class TestVocabularySchema:
    """Тесты схемы vocabulary"""

    def test_vocabulary_schema_structure(self):
        """Тест структуры схемы vocabulary"""
        schema = StandardContentSchemas.vocabulary_schema()

        assert 'type' in schema
        assert schema['type'] == 'object'
        assert 'properties' in schema
        assert 'words' in schema['properties']
        assert 'required' in schema
        assert 'words' in schema['required']

    def test_vocabulary_schema_words_array(self):
        """Тест массива words в схеме"""
        schema = StandardContentSchemas.vocabulary_schema()
        words = schema['properties']['words']

        assert words['type'] == 'array'
        assert 'items' in words
        assert words['minItems'] == 1
        assert words['maxItems'] == 50

    def test_vocabulary_schema_word_properties(self):
        """Тест свойств слова"""
        schema = StandardContentSchemas.vocabulary_schema()
        word_item = schema['properties']['words']['items']

        assert 'word' in word_item['properties']
        assert 'translation' in word_item['properties']
        assert word_item['required'] == ['word', 'translation']

    def test_vocabulary_schema_settings(self):
        """Тест настроек в схеме"""
        schema = StandardContentSchemas.vocabulary_schema()
        settings = schema['properties']['settings']

        assert settings['type'] == 'object'
        assert 'review_mode' in settings['properties']
        assert 'show_translation' in settings['properties']


class TestGrammarSchema:
    """Тесты схемы grammar"""

    def test_grammar_schema_structure(self):
        """Тест структуры схемы grammar"""
        schema = StandardContentSchemas.grammar_schema()

        assert schema['type'] == 'object'
        assert 'title' in schema['properties']
        assert 'content' in schema['properties']
        assert schema['required'] == ['title', 'content']

    def test_grammar_schema_rules(self):
        """Тест правил грамматики"""
        schema = StandardContentSchemas.grammar_schema()
        rules = schema['properties']['rules']

        assert rules['type'] == 'array'
        assert rules['maxItems'] == 20

    def test_grammar_schema_exercises(self):
        """Тест упражнений"""
        schema = StandardContentSchemas.grammar_schema()
        exercises = schema['properties']['exercises']

        assert exercises['type'] == 'array'
        exercise_item = exercises['items']
        assert 'type' in exercise_item['properties']
        assert 'question' in exercise_item['properties']
        assert 'answer' in exercise_item['properties']


class TestQuizSchema:
    """Тесты схемы quiz"""

    def test_quiz_schema_structure(self):
        """Тест структуры схемы quiz"""
        schema = StandardContentSchemas.quiz_schema()

        assert schema['type'] == 'object'
        assert 'questions' in schema['properties']
        assert schema['required'] == ['questions']

    def test_quiz_schema_questions(self):
        """Тест вопросов"""
        schema = StandardContentSchemas.quiz_schema()
        questions = schema['properties']['questions']

        assert questions['type'] == 'array'
        assert questions['minItems'] == 1
        assert questions['maxItems'] == 50

    def test_quiz_schema_question_properties(self):
        """Тест свойств вопроса"""
        schema = StandardContentSchemas.quiz_schema()
        question_item = schema['properties']['questions']['items']

        assert 'question' in question_item['properties']
        assert 'options' in question_item['properties']
        assert 'correct' in question_item['properties']
        assert question_item['required'] == ['question', 'options', 'correct']

    def test_quiz_schema_settings(self):
        """Тест настроек quiz"""
        schema = StandardContentSchemas.quiz_schema()
        settings = schema['properties']['settings']

        assert 'time_limit' in settings['properties']
        assert 'passing_score' in settings['properties']
        assert 'shuffle_questions' in settings['properties']


class TestMatchingSchema:
    """Тесты схемы matching"""

    def test_matching_schema_structure(self):
        """Тест структуры схемы matching"""
        schema = StandardContentSchemas.matching_schema()

        assert schema['type'] == 'object'
        assert 'pairs' in schema['properties']
        assert schema['required'] == ['pairs']

    def test_matching_schema_pairs(self):
        """Тест пар"""
        schema = StandardContentSchemas.matching_schema()
        pairs = schema['properties']['pairs']

        assert pairs['type'] == 'array'
        assert pairs['minItems'] == 2
        assert pairs['maxItems'] == 20

    def test_matching_schema_pair_properties(self):
        """Тест свойств пары"""
        schema = StandardContentSchemas.matching_schema()
        pair_item = schema['properties']['pairs']['items']

        assert 'left' in pair_item['properties']
        assert 'right' in pair_item['properties']
        assert pair_item['required'] == ['left', 'right']


class TestTextSchema:
    """Тесты схемы text"""

    def test_text_schema_structure(self):
        """Тест структуры схемы text"""
        schema = StandardContentSchemas.text_schema()

        assert schema['type'] == 'object'
        assert 'content' in schema['properties']
        assert schema['required'] == ['content']

    def test_text_schema_comprehension_questions(self):
        """Тест вопросов на понимание"""
        schema = StandardContentSchemas.text_schema()
        questions = schema['properties']['comprehension_questions']

        assert questions['type'] == 'array'
        assert questions['maxItems'] == 20

    def test_text_schema_vocabulary_highlight(self):
        """Тест подсветки словаря"""
        schema = StandardContentSchemas.text_schema()
        vocab = schema['properties']['vocabulary_highlight']

        assert vocab['type'] == 'array'
        assert vocab['maxItems'] == 100


class TestCardSchema:
    """Тесты схемы card"""

    def test_card_schema_structure(self):
        """Тест структуры схемы card"""
        schema = StandardContentSchemas.card_schema()

        assert schema['type'] == 'object'
        assert 'collection_id' in schema['properties']
        assert 'word_ids' in schema['properties']

    def test_card_schema_srs_settings(self):
        """Тест SRS настроек"""
        schema = StandardContentSchemas.card_schema()
        srs_settings = schema['properties']['srs_settings']

        assert 'min_cards_required' in srs_settings['properties']
        assert 'min_accuracy_required' in srs_settings['properties']
        assert 'review_directions' in srs_settings['properties']


class TestFinalTestSchema:
    """Тесты схемы final_test"""

    def test_final_test_schema_structure(self):
        """Тест структуры схемы final_test"""
        schema = StandardContentSchemas.final_test_schema()

        assert schema['type'] == 'object'
        assert 'sections' in schema['properties']
        assert schema['required'] == ['sections']

    def test_final_test_schema_sections(self):
        """Тест секций"""
        schema = StandardContentSchemas.final_test_schema()
        sections = schema['properties']['sections']

        assert sections['type'] == 'array'
        assert sections['minItems'] == 1
        assert sections['maxItems'] == 10

    def test_final_test_schema_section_properties(self):
        """Тест свойств секции"""
        schema = StandardContentSchemas.final_test_schema()
        section_item = schema['properties']['sections']['items']

        assert 'name' in section_item['properties']
        assert 'type' in section_item['properties']
        assert 'content' in section_item['properties']
        assert section_item['required'] == ['name', 'type', 'content']


class TestGetSchemaForType:
    """Тесты получения схемы по типу"""

    def test_get_schema_for_vocabulary(self):
        """Тест получения схемы vocabulary"""
        schema = StandardContentSchemas.get_schema_for_type('vocabulary')
        assert 'words' in schema['properties']

    def test_get_schema_for_grammar(self):
        """Тест получения схемы grammar"""
        schema = StandardContentSchemas.get_schema_for_type('grammar')
        assert 'title' in schema['properties']
        assert 'content' in schema['properties']

    def test_get_schema_for_quiz(self):
        """Тест получения схемы quiz"""
        schema = StandardContentSchemas.get_schema_for_type('quiz')
        assert 'questions' in schema['properties']

    def test_get_schema_for_matching(self):
        """Тест получения схемы matching"""
        schema = StandardContentSchemas.get_schema_for_type('matching')
        assert 'pairs' in schema['properties']

    def test_get_schema_for_text(self):
        """Тест получения схемы text"""
        schema = StandardContentSchemas.get_schema_for_type('text')
        assert 'content' in schema['properties']

    def test_get_schema_for_card(self):
        """Тест получения схемы card"""
        schema = StandardContentSchemas.get_schema_for_type('card')
        assert 'word_ids' in schema['properties'] or 'collection_id' in schema['properties']

    def test_get_schema_for_final_test(self):
        """Тест получения схемы final_test"""
        schema = StandardContentSchemas.get_schema_for_type('final_test')
        assert 'sections' in schema['properties']

    def test_get_schema_for_unknown_type(self):
        """Тест получения схемы для неизвестного типа"""
        schema = StandardContentSchemas.get_schema_for_type('unknown')
        assert schema == {}


class TestNormalizeVocabularyContent:
    """Тесты нормализации vocabulary контента"""

    def test_normalize_vocabulary_dict_with_words(self):
        """Тест нормализации словаря с ключом words"""
        content = {
            'words': [
                {'word': 'hello', 'translation': 'привет'},
                {'word': 'world', 'translation': 'мир'}
            ],
            'settings': {'show_translation': True}
        }

        result = StandardContentSchemas.normalize_content('vocabulary', content)

        assert 'words' in result
        assert len(result['words']) == 2
        assert result['words'][0]['word'] == 'hello'
        assert result['words'][0]['translation'] == 'привет'
        assert 'settings' in result

    def test_normalize_vocabulary_list(self):
        """Тест нормализации прямого списка слов"""
        content = [
            {'word': 'cat', 'translation': 'кот'},
            {'word': 'dog', 'translation': 'собака'}
        ]

        result = StandardContentSchemas.normalize_content('vocabulary', content)

        assert 'words' in result
        assert len(result['words']) == 2
        assert result['words'][0]['word'] == 'cat'

    def test_normalize_vocabulary_alternative_keys(self):
        """Тест нормализации с альтернативными ключами front/back"""
        content = {
            'words': [
                {'front': 'apple', 'back': 'яблоко'}
            ]
        }

        result = StandardContentSchemas.normalize_content('vocabulary', content)

        assert result['words'][0]['word'] == 'apple'
        assert result['words'][0]['translation'] == 'яблоко'

    def test_normalize_vocabulary_with_optional_fields(self):
        """Тест нормализации с опциональными полями"""
        content = {
            'words': [
                {
                    'word': 'test',
                    'translation': 'тест',
                    'example': 'This is a test',
                    'hint': 'Подсказка',
                    'pronunciation': 'test'
                }
            ]
        }

        result = StandardContentSchemas.normalize_content('vocabulary', content)

        word = result['words'][0]
        assert 'example' in word
        assert 'hint' in word
        assert 'pronunciation' in word


class TestNormalizeGrammarContent:
    """Тесты нормализации grammar контента"""

    def test_normalize_grammar_basic(self):
        """Тест базовой нормализации grammar"""
        content = {
            'title': 'Present Simple',
            'content': 'Test content'
        }

        result = StandardContentSchemas.normalize_content('grammar', content)

        assert result['title'] == 'Present Simple'
        assert result['content'] == 'Test content'

    def test_normalize_grammar_with_rules(self):
        """Тест нормализации с правилами"""
        content = {
            'title': 'Test',
            'content': 'Test',
            'rules': ['Rule 1', 'Rule 2']
        }

        result = StandardContentSchemas.normalize_content('grammar', content)

        assert 'rules' in result
        assert len(result['rules']) == 2

    def test_normalize_grammar_with_exercises(self):
        """Тест нормализации с упражнениями"""
        content = {
            'title': 'Test',
            'content': 'Test',
            'exercises': [
                {'type': 'fill_blank', 'question': 'Q1', 'answer': 'A1'}
            ]
        }

        result = StandardContentSchemas.normalize_content('grammar', content)

        assert 'exercises' in result
        assert len(result['exercises']) == 1


class TestNormalizeQuizContent:
    """Тесты нормализации quiz контента"""

    def test_normalize_quiz_basic(self):
        """Тест базовой нормализации quiz"""
        content = {
            'questions': [
                {'question': 'Q1', 'options': ['A', 'B'], 'correct': 0}
            ]
        }

        result = StandardContentSchemas.normalize_content('quiz', content)

        assert 'questions' in result
        assert len(result['questions']) == 1

    def test_normalize_quiz_adds_default_type(self):
        """Тест что добавляется тип по умолчанию"""
        content = {
            'questions': [
                {'question': 'Q1', 'options': ['A', 'B'], 'correct': 0}
            ]
        }

        result = StandardContentSchemas.normalize_content('quiz', content)

        # Проверяем что добавлен тип по умолчанию
        assert result['questions'][0]['type'] == 'multiple_choice'

    def test_normalize_quiz_preserves_existing_type(self):
        """Тест что существующий тип сохраняется"""
        content = {
            'questions': [
                {'question': 'Q1', 'options': ['A', 'B'], 'correct': 0, 'type': 'true_false'}
            ]
        }

        result = StandardContentSchemas.normalize_content('quiz', content)

        assert result['questions'][0]['type'] == 'true_false'


class TestNormalizeMatchingContent:
    """Тесты нормализации matching контента"""

    def test_normalize_matching_basic(self):
        """Тест базовой нормализации matching"""
        content = {
            'pairs': [
                {'left': 'hello', 'right': 'привет'},
                {'left': 'world', 'right': 'мир'}
            ]
        }

        result = StandardContentSchemas.normalize_content('matching', content)

        assert 'pairs' in result
        assert len(result['pairs']) == 2

    def test_normalize_matching_with_settings(self):
        """Тест нормализации с настройками"""
        content = {
            'pairs': [{'left': 'a', 'right': 'б'}],
            'settings': {'shuffle_items': True}
        }

        result = StandardContentSchemas.normalize_content('matching', content)

        assert 'settings' in result
        assert result['settings']['shuffle_items'] is True


class TestNormalizeTextContent:
    """Тесты нормализации text контента"""

    def test_normalize_text_with_content_key(self):
        """Тест нормализации с ключом content"""
        content = {
            'content': 'Test text content'
        }

        result = StandardContentSchemas.normalize_content('text', content)

        assert result['content'] == 'Test text content'

    def test_normalize_text_with_text_key(self):
        """Тест нормализации с ключом text (альтернативный)"""
        content = {
            'text': 'Alternative text content'
        }

        result = StandardContentSchemas.normalize_content('text', content)

        assert result['content'] == 'Alternative text content'

    def test_normalize_text_with_optional_fields(self):
        """Тест нормализации с опциональными полями"""
        content = {
            'content': 'Text',
            'title': 'Article Title',
            'author': 'John Doe',
            'vocabulary_highlight': ['word1', 'word2']
        }

        result = StandardContentSchemas.normalize_content('text', content)

        assert 'title' in result
        assert 'author' in result
        assert 'vocabulary_highlight' in result


class TestNormalizeCardContent:
    """Тесты нормализации card контента"""

    def test_normalize_card_basic(self):
        """Тест базовой нормализации card"""
        content = {
            'collection_id': 1,
            'word_ids': [1, 2, 3]
        }

        result = StandardContentSchemas.normalize_content('card', content)

        assert 'collection_id' in result
        assert 'word_ids' in result
        assert len(result['word_ids']) == 3

    def test_normalize_card_with_srs_settings(self):
        """Тест нормализации с SRS настройками"""
        content = {
            'collection_id': 1,
            'srs_settings': {
                'min_cards_required': 10,
                'new_cards_limit': 20
            }
        }

        result = StandardContentSchemas.normalize_content('card', content)

        assert 'srs_settings' in result
        assert result['srs_settings']['min_cards_required'] == 10


class TestNormalizeUnknownType:
    """Тесты нормализации неизвестного типа"""

    def test_normalize_unknown_type_returns_original(self):
        """Тест что неизвестный тип возвращает оригинальный контент"""
        content = {'some': 'data'}

        result = StandardContentSchemas.normalize_content('unknown_type', content)

        assert result == content
