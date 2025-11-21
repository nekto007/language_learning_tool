"""
Tests for admin forms
Тесты форм администратора
"""
import pytest
from app.admin.form import CEFRLevelForm, ModuleForm, LessonForm, TextLessonForm, MatchingLessonForm, QuizLessonForm, GrammarLessonForm


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
            form = CEFRLevelForm(
                code='',
                name=''
            )
            assert not form.validate()
            assert 'code' in form.errors
            assert 'name' in form.errors


class TestModuleForm:
    """Тесты формы Module"""

    def test_create_form(self, app, test_level):
        """Тест создания формы"""
        with app.test_request_context():
            form = ModuleForm(
                level_id=test_level.id,
                number=1,
                title='Test Module',
                description='Test description'
            )
            assert form.level_id.data == test_level.id
            assert form.number.data == 1
            assert form.title.data == 'Test Module'

    def test_form_has_required_fields(self, app):
        """Тест наличия обязательных полей в форме"""
        with app.test_request_context():
            form = ModuleForm()
            assert hasattr(form, 'level_id')
            assert hasattr(form, 'number')
            assert hasattr(form, 'title')
            assert hasattr(form, 'description')


class TestLessonForm:
    """Тесты формы Lesson"""

    def test_create_form(self, app, test_module):
        """Тест создания формы"""
        with app.test_request_context():
            form = LessonForm(
                module_id=test_module.id,
                number=1,
                title='Test Lesson',
                type='vocabulary',
                order=1,
                description='Test description'
            )
            assert form.module_id.data == test_module.id
            assert form.number.data == 1
            assert form.title.data == 'Test Lesson'
            assert form.type.data == 'vocabulary'

    def test_form_has_required_fields(self, app):
        """Тест наличия обязательных полей в форме"""
        with app.test_request_context():
            form = LessonForm()
            assert hasattr(form, 'module_id')
            assert hasattr(form, 'number')
            assert hasattr(form, 'title')
            assert hasattr(form, 'type')
            assert hasattr(form, 'order')
            assert hasattr(form, 'description')
            assert hasattr(form, 'collection_id')
            assert hasattr(form, 'book_id')

    def test_lesson_type_choices(self, app):
        """Тест доступных типов уроков"""
        with app.test_request_context():
            form = LessonForm()
            expected_types = ['vocabulary', 'grammar', 'quiz', 'matching', 'text', 'card', 'checkpoint']
            actual_types = [choice[0] for choice in form.type.choices]
            assert all(t in actual_types for t in expected_types)


class TestTextLessonForm:
    """Тесты формы TextLesson"""

    def test_create_form(self, app, test_book):
        """Тест создания формы"""
        with app.test_request_context():
            form = TextLessonForm(
                book_id=test_book.id,
                starting_paragraph=1,
                ending_paragraph=10
            )
            assert form.book_id.data == test_book.id
            assert form.starting_paragraph.data == 1
            assert form.ending_paragraph.data == 10

    def test_form_default_values(self, app):
        """Тест значений по умолчанию"""
        with app.test_request_context():
            form = TextLessonForm()
            assert form.starting_paragraph.data is None or form.starting_paragraph.data == 0
            assert form.ending_paragraph.data is None or form.ending_paragraph.data == 0


class TestMatchingLessonForm:
    """Тесты формы MatchingLesson"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = MatchingLessonForm(
                time_limit=60
            )
            assert form.time_limit.data == 60

    def test_form_default_values(self, app):
        """Тест значений по умолчанию"""
        with app.test_request_context():
            form = MatchingLessonForm()
            assert form.time_limit.data is None or form.time_limit.data == 0


class TestQuizLessonForm:
    """Тесты формы QuizLesson"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = QuizLessonForm(
                passing_score=80
            )
            assert form.passing_score.data == 80

    def test_form_default_values(self, app):
        """Тест значений по умолчанию"""
        with app.test_request_context():
            form = QuizLessonForm()
            assert form.passing_score.data is None or form.passing_score.data == 70

    def test_form_validation_score_range(self, app):
        """Тест валидации диапазона проходного балла"""
        with app.test_request_context():
            form = QuizLessonForm(passing_score=150)
            assert not form.validate()
            assert 'passing_score' in form.errors


class TestGrammarLessonForm:
    """Тесты формы GrammarLesson"""

    def test_create_form(self, app):
        """Тест создания формы"""
        with app.test_request_context():
            form = GrammarLessonForm(
                rule='Test grammar rule'
            )
            assert form.rule.data == 'Test grammar rule'

    def test_form_validation_required_fields(self, app):
        """Тест валидации обязательных полей"""
        with app.test_request_context():
            form = GrammarLessonForm(rule='')
            assert not form.validate()
            assert 'rule' in form.errors
