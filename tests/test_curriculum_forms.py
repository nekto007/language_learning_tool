"""
Tests for curriculum forms
Тесты форм учебного плана
"""
import pytest
from app.curriculum.form import (
    CEFRLevelForm, ModuleForm, LessonForm, QuizForm, MatchingForm,
    TextReadingForm, AnkiCardsForm, LessonFeedbackForm, GrammarExerciseForm,
    VocabularyReviewForm, ImportCurriculumForm, CurriculumSearchForm
)


class TestCEFRLevelForm:
    """Тесты формы CEFRLevel"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = CEFRLevelForm(
                code='A1',
                name='Beginner',
                description='Basic level',
                order=1
            )
            assert form.code.data == 'A1'
            assert form.name.data == 'Beginner'
            assert form.description.data == 'Basic level'
            assert form.order.data == 1

    def test_form_validation_required_fields(self, app):
        """Тест валидации обязательных полей"""
        with app.test_request_context():
            form = CEFRLevelForm(code='', name='')
            assert not form.validate()
            assert 'code' in form.errors
            assert 'name' in form.errors

    def test_form_validation_code_length(self, app):
        """Тест валидации длины кода"""
        with app.test_request_context():
            form = CEFRLevelForm(code='A', name='Test')
            assert not form.validate()
            assert 'code' in form.errors


class TestModuleForm:
    """Тесты формы Module"""

    def test_create_form_with_choices(self, app, db_session, test_level):
        """Тест создания формы с выбором уровней"""
        with app.app_context():
            form = ModuleForm(
                level_id=test_level.id,
                number=1,
                title='Test Module',
                description='Test description'
            )
            assert form.level_id.data == test_level.id
            assert form.number.data == 1
            assert form.title.data == 'Test Module'
            assert len(form.level_id.choices) > 0

    def test_form_validation_required_fields(self, app, db_session):
        """Тест валидации обязательных полей"""
        with app.app_context():
            form = ModuleForm(level_id='', number='', title='')
            assert not form.validate()
            assert 'level_id' in form.errors
            assert 'number' in form.errors
            assert 'title' in form.errors


class TestLessonForm:
    """Тесты формы Lesson"""

    def test_create_form_with_choices(self, app, db_session, test_module):
        """Тест создания формы с выбором модулей"""
        with app.app_context():
            form = LessonForm(
                module_id=test_module.id,
                number=1,
                type='vocabulary',
                title='Test Lesson',
                order=1
            )
            assert form.module_id.data == test_module.id
            assert form.number.data == 1
            assert form.title.data == 'Test Lesson'
            assert len(form.module_id.choices) > 0
            assert len(form.collection_id.choices) >= 1  # At least the default option
            assert len(form.book_id.choices) >= 1  # At least the default option

    def test_form_validation_required_fields(self, app, db_session):
        """Тест валидации обязательных полей"""
        with app.app_context():
            form = LessonForm(module_id='', number='', type='', title='')
            assert not form.validate()
            assert 'module_id' in form.errors
            assert 'number' in form.errors
            assert 'type' in form.errors
            assert 'title' in form.errors

    def test_lesson_type_choices(self, app, db_session):
        """Тест доступных типов уроков"""
        with app.app_context():
            form = LessonForm()
            expected_types = ['vocabulary', 'grammar', 'quiz', 'matching', 'text', 'anki_cards', 'checkpoint']
            actual_types = [choice[0] for choice in form.type.choices]
            assert all(t in actual_types for t in expected_types)


class TestQuizForm:
    """Тесты формы Quiz"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = QuizForm()
            assert form.submit is not None


class TestMatchingForm:
    """Тесты формы Matching"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = MatchingForm()
            assert form.submit is not None


class TestTextReadingForm:
    """Тесты формы TextReading"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = TextReadingForm(completed=True)
            assert form.completed.data is True

    def test_form_validation_required(self, app):
        """Тест валидации обязательного поля"""
        with app.test_request_context():
            form = TextReadingForm(completed=False)
            assert not form.validate()
            assert 'completed' in form.errors


class TestAnkiCardsForm:
    """Тесты формы AnkiCards"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = AnkiCardsForm()
            assert form.submit is not None


class TestLessonFeedbackForm:
    """Тесты формы LessonFeedback"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = LessonFeedbackForm(
                rating=4,
                comments='Great lesson!'
            )
            assert form.rating.data == 4
            assert form.comments.data == 'Great lesson!'

    def test_rating_choices(self, app):
        """Тест вариантов оценки"""
        with app.test_request_context():
            form = LessonFeedbackForm()
            ratings = [choice[0] for choice in form.rating.choices]
            assert ratings == [1, 2, 3, 4, 5]


class TestGrammarExerciseForm:
    """Тесты формы GrammarExercise"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = GrammarExerciseForm()
            assert form.submit is not None


class TestVocabularyReviewForm:
    """Тесты формы VocabularyReview"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = VocabularyReviewForm(completed=True)
            assert form.completed.data is True

    def test_form_validation_required(self, app):
        """Тест валидации обязательного поля"""
        with app.test_request_context():
            form = VocabularyReviewForm(completed=False)
            assert not form.validate()
            assert 'completed' in form.errors


class TestImportCurriculumForm:
    """Тесты формы ImportCurriculum"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = ImportCurriculumForm()
            assert form.file is not None
            assert form.submit is not None


class TestCurriculumSearchForm:
    """Тесты формы CurriculumSearch"""

    def test_create_form_with_choices(self, app, db_session, test_level):
        """Тест создания формы с выбором уровней"""
        with app.app_context():
            form = CurriculumSearchForm()
            assert len(form.level.choices) >= 1  # At least the default "All Levels"
            assert len(form.module.choices) >= 1  # At least the default "All Modules"

    def test_lesson_type_choices(self, app, db_session):
        """Тест вариантов типов уроков"""
        with app.app_context():
            form = CurriculumSearchForm()
            expected_types = ['', 'vocabulary', 'grammar', 'quiz', 'matching', 'text', 'anki_cards', 'checkpoint']
            actual_types = [choice[0] for choice in form.lesson_type.choices]
            assert all(t in actual_types for t in expected_types)

    def test_form_with_search_query(self, app, db_session):
        """Тест формы с поисковым запросом"""
        with app.app_context():
            form = CurriculumSearchForm(search='test query')
            assert form.search.data == 'test query'

    def test_form_with_level_id_in_formdata(self, app, db_session, test_level, test_module):
        """Тест заполнения модулей на основе выбранного level_id"""
        with app.app_context():
            # Создаем форму с formdata, содержащим level
            from werkzeug.datastructures import MultiDict
            formdata = MultiDict([('level', str(test_level.id))])
            form = CurriculumSearchForm(formdata=formdata)

            # Проверяем что module choices заполнены
            module_ids = [choice[0] for choice in form.module.choices]
            # Должен быть хотя бы test_module
            assert test_module.id in module_ids
