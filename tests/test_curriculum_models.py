"""
Tests for curriculum models
Проверка моделей БД
"""
import pytest
from datetime import datetime, timedelta, timezone
from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress, LessonAttempt


class TestCEFRLevelModel:
    """Тесты модели уровня CEFR"""

    def test_create_level(self, app, db_session):
        """Тест создания уровня"""
        with app.app_context():
            level = CEFRLevel(
                code='A1',
                name='Beginner',
                description='Beginner level',
                order=1
            )
            db_session.add(level)
            db_session.commit()

            assert level.id is not None
            assert level.code == 'A1'
            assert level.name == 'Beginner'

    def test_level_modules_relationship(self, app, db_session, test_level, test_module):
        """Тест связи уровень-модули"""
        with app.app_context():
            assert test_module in test_level.modules
            assert test_module.level.id == test_level.id

    def test_level_repr(self, app, db_session, test_level):
        """Тест __repr__ метода"""
        with app.app_context():
            repr_str = repr(test_level)
            assert 'CEFRLevel' in repr_str
            assert test_level.code in repr_str
            assert test_level.name in repr_str


class TestModuleModel:
    """Тесты модели модуля"""

    def test_create_module(self, app, db_session, test_level):
        """Тест создания модуля"""
        with app.app_context():
            module = Module(
                level_id=test_level.id,
                number=1,
                title='Test Module',
                description='Test description',
                raw_content={'test': 'data'}
            )
            db_session.add(module)
            db_session.commit()

            assert module.id is not None
            assert module.number == 1
            assert module.title == 'Test Module'

    def test_module_lessons_relationship(self, app, db_session, test_module, test_lesson_vocabulary):
        """Тест связи модуль-уроки"""
        with app.app_context():
            assert test_lesson_vocabulary in test_module.lessons
            assert test_lesson_vocabulary.module.id == test_module.id

    def test_module_raw_content_json(self, app, db_session, test_module):
        """Тест JSON поля raw_content"""
        with app.app_context():
            test_module.raw_content = {
                'module': {
                    'id': 1,
                    'title': 'Test',
                    'lessons': []
                }
            }
            db_session.commit()

            module = db_session.get(Module, test_module.id)
            assert module.raw_content is not None
            assert isinstance(module.raw_content, dict)
            assert 'module' in module.raw_content

    def test_module_repr(self, app, db_session, test_module):
        """Тест __repr__ метода"""
        with app.app_context():
            repr_str = repr(test_module)
            assert 'Module' in repr_str
            assert str(test_module.number) in repr_str
            assert test_module.title in repr_str

    def test_check_prerequisites_no_prereqs(self, app, db_session, test_module, test_user):
        """Тест check_prerequisites без предусловий"""
        with app.app_context():
            # Module without prerequisites
            is_accessible, reasons = test_module.check_prerequisites(test_user.id)
            assert is_accessible is True
            assert reasons == []

    def test_check_prerequisites_with_prereqs(self, app, db_session, test_level, test_user):
        """Тест check_prerequisites с предусловиями"""
        with app.app_context():
            # Create prereq module
            prereq_module = Module(
                level_id=test_level.id,
                number=1,
                title='Prereq Module',
                raw_content={}
            )
            db_session.add(prereq_module)
            db_session.commit()

            # Create module with prerequisites
            module = Module(
                level_id=test_level.id,
                number=2,
                title='Main Module',
                raw_content={},
                prerequisites=[
                    {
                        'type': 'module',
                        'id': prereq_module.id,
                        'min_score': 70
                    }
                ]
            )
            db_session.add(module)
            db_session.commit()

            # User hasn't completed prereq
            is_accessible, reasons = module.check_prerequisites(test_user.id)
            assert is_accessible is False
            assert len(reasons) > 0
            assert 'Prereq Module' in reasons[0]

    def test_check_prerequisites_low_score(self, app, db_session, test_level, test_user):
        """Тест check_prerequisites когда пользователь завершил модуль но с низкой оценкой"""
        with app.app_context():
            # Create prereq module with lessons
            prereq_module = Module(
                level_id=test_level.id,
                number=1,
                title='Prereq Module',
                raw_content={}
            )
            db_session.add(prereq_module)
            db_session.flush()

            # Add lessons to prereq module
            lesson1 = Lessons(
                module_id=prereq_module.id,
                number=1,
                type='vocabulary',
                title='Lesson 1',
                content={'words': []},
                order=1
            )
            lesson2 = Lessons(
                module_id=prereq_module.id,
                number=2,
                type='vocabulary',
                title='Lesson 2',
                content={'words': []},
                order=2
            )
            db_session.add_all([lesson1, lesson2])
            db_session.flush()

            # Create progress with low scores (completed but < 70%)
            progress1 = LessonProgress(
                user_id=test_user.id,
                lesson_id=lesson1.id,
                status='completed',
                score=50.0
            )
            progress2 = LessonProgress(
                user_id=test_user.id,
                lesson_id=lesson2.id,
                status='completed',
                score=60.0
            )
            db_session.add_all([progress1, progress2])
            db_session.commit()

            # Create module with prerequisites requiring 70% score
            module = Module(
                level_id=test_level.id,
                number=2,
                title='Main Module',
                raw_content={},
                prerequisites=[
                    {
                        'type': 'module',
                        'id': prereq_module.id,
                        'min_score': 70
                    }
                ]
            )
            db_session.add(module)
            db_session.commit()

            # Should not be accessible due to low score
            is_accessible, reasons = module.check_prerequisites(test_user.id)
            assert is_accessible is False
            assert len(reasons) > 0
            # Check that the reason mentions the score requirement
            assert any('70' in reason or 'Score' in reason for reason in reasons)


class TestLessonsModel:
    """Тесты модели урока"""

    def test_create_lesson(self, app, db_session, test_module):
        """Тест создания урока"""
        with app.app_context():
            lesson = Lessons(
                module_id=test_module.id,
                number=1,
                title='Test Lesson',
                type='vocabulary',
                order=0,
                content={'vocabulary': []}
            )
            db_session.add(lesson)
            db_session.commit()

            assert lesson.id is not None
            assert lesson.title == 'Test Lesson'
            assert lesson.type == 'vocabulary'

    def test_lesson_content_json(self, app, db_session, test_lesson_vocabulary):
        """Тест JSON поля content"""
        with app.app_context():
            assert test_lesson_vocabulary.content is not None
            assert isinstance(test_lesson_vocabulary.content, dict)

    def test_lesson_input_mode_from_module(self, app, db_session, test_module, test_lesson_vocabulary):
        """Тест получения input_mode из модуля"""
        with app.app_context():
            test_module.input_mode = 'advanced'
            db_session.commit()

            assert test_lesson_vocabulary.input_mode == 'advanced'

    def test_is_card_lesson(self, app, db_session, test_module):
        """Тест свойства is_card_lesson"""
        with app.app_context():
            # Create card lesson
            card_lesson = Lessons(
                module_id=test_module.id,
                number=5,
                title='Card Lesson',
                type='card',
                order=4,
                content={}
            )
            db_session.add(card_lesson)

            # Create non-card lesson
            vocab_lesson = Lessons(
                module_id=test_module.id,
                number=6,
                title='Vocab Lesson',
                type='vocabulary',
                order=5,
                content={}
            )
            db_session.add(vocab_lesson)
            db_session.commit()

            assert card_lesson.is_card_lesson is True
            assert vocab_lesson.is_card_lesson is False

    def test_get_srs_settings_card_lesson(self, app, db_session, test_module):
        """Тест get_srs_settings для card урока"""
        with app.app_context():
            card_lesson = Lessons(
                module_id=test_module.id,
                number=5,
                title='Card Lesson',
                type='card',
                order=4,
                content={},
                min_cards_required=15,
                min_accuracy_required=85
            )
            db_session.add(card_lesson)
            db_session.commit()

            settings = card_lesson.get_srs_settings()
            assert settings is not None
            assert settings['min_cards_required'] == 15
            assert settings['min_accuracy_required'] == 85
            assert 'new_cards_limit' in settings

    def test_get_srs_settings_non_card_lesson(self, app, db_session, test_lesson_vocabulary):
        """Тест get_srs_settings для не-card урока"""
        with app.app_context():
            settings = test_lesson_vocabulary.get_srs_settings()
            assert settings is None

    def test_get_srs_settings_with_content_override(self, app, db_session, test_module):
        """Тест get_srs_settings с переопределением в content"""
        with app.app_context():
            card_lesson = Lessons(
                module_id=test_module.id,
                number=5,
                title='Card Lesson',
                type='card',
                order=4,
                content={
                    'srs_settings': {
                        'new_cards_limit': 20,
                        'show_hint_time': 10
                    }
                }
            )
            db_session.add(card_lesson)
            db_session.commit()

            settings = card_lesson.get_srs_settings()
            assert settings['new_cards_limit'] == 20
            assert settings['show_hint_time'] == 10

    def test_lesson_repr(self, app, db_session, test_lesson_vocabulary):
        """Тест __repr__ метода"""
        with app.app_context():
            repr_str = repr(test_lesson_vocabulary)
            assert 'Lesson' in repr_str
            assert str(test_lesson_vocabulary.number) in repr_str
            assert test_lesson_vocabulary.title in repr_str

    def test_validate_content_schema_valid(self, app, db_session, test_lesson_vocabulary):
        """Тест validate_content_schema для валидного контента"""
        with app.app_context():
            is_valid, error_msg, cleaned_data = test_lesson_vocabulary.validate_content_schema()
            assert is_valid is True
            assert error_msg is None

    def test_validate_content_schema_invalid(self, app, db_session, test_module):
        """Тест validate_content_schema для невалидного контента"""
        with app.app_context():
            # Create lesson with invalid content
            lesson = Lessons(
                module_id=test_module.id,
                number=10,
                title='Invalid Lesson',
                type='vocabulary',
                order=9,
                content={'words': []}  # Empty array - invalid
            )
            db_session.add(lesson)
            db_session.commit()

            # validate_content_schema catches ValidationError and returns tuple
            result = lesson.validate_content_schema()
            is_valid = result[0]
            error_msg = result[1]
            assert is_valid is False
            assert error_msg is not None


class TestLessonProgressModel:
    """Тесты модели прогресса урока"""

    def test_create_progress(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест создания прогресса"""
        with app.app_context():
            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='in_progress',
                score=50.0
            )
            db_session.add(progress)
            db_session.commit()

            assert progress.id is not None
            assert progress.score == 50.0
            assert progress.status == 'in_progress'
            assert progress.attempts == []  # Empty relationship initially

    def test_progress_relationships(self, app, db_session, test_lesson_progress, test_user, test_lesson_vocabulary):
        """Тест связей прогресса"""
        with app.app_context():
            assert test_lesson_progress.user.id == test_user.id
            assert test_lesson_progress.lesson.id == test_lesson_vocabulary.id

    def test_progress_repr(self, app, db_session, test_lesson_progress):
        """Тест __repr__ метода"""
        with app.app_context():
            repr_str = repr(test_lesson_progress)
            assert 'LessonProgress' in repr_str
            assert str(test_lesson_progress.lesson_id) in repr_str
            assert test_lesson_progress.status in repr_str

    def test_rounded_score(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест свойства rounded_score"""
        with app.app_context():
            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='completed',
                score=85.7
            )
            db_session.add(progress)
            db_session.commit()

            assert progress.rounded_score == 86

    def test_rounded_score_none(self, app, db_session, test_user, test_lesson_vocabulary):
        """Тест rounded_score когда score is None"""
        with app.app_context():
            progress = LessonProgress(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                status='in_progress'
            )
            progress.score = None
            db_session.add(progress)
            db_session.commit()

            assert progress.rounded_score == 0

    def test_set_score(self, app, db_session, test_lesson_progress):
        """Тест метода set_score"""
        with app.app_context():
            # Normal value
            test_lesson_progress.set_score(75.8)
            assert test_lesson_progress.score == 76.0

            # Value above 100
            test_lesson_progress.set_score(150)
            assert test_lesson_progress.score == 100.0

            # Value below 0
            test_lesson_progress.set_score(-10)
            assert test_lesson_progress.score == 0.0

            # None value
            test_lesson_progress.set_score(None)
            assert test_lesson_progress.score == 0.0


class TestLessonAttemptModel:
    """Тесты модели попытки урока"""

    def test_create_attempt_first(self, app, db_session, test_user, test_lesson_vocabulary, test_lesson_progress):
        """Тест создания первой попытки"""
        with app.app_context():
            attempt = LessonAttempt.create_attempt(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                lesson_progress_id=test_lesson_progress.id
            )
            db_session.commit()

            assert attempt.id is not None
            assert attempt.attempt_number == 1
            assert attempt.user_id == test_user.id
            assert attempt.lesson_id == test_lesson_vocabulary.id

    def test_create_attempt_second(self, app, db_session, test_user, test_lesson_vocabulary, test_lesson_progress):
        """Тест создания второй попытки"""
        with app.app_context():
            # First attempt
            attempt1 = LessonAttempt.create_attempt(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                lesson_progress_id=test_lesson_progress.id
            )
            db_session.commit()

            # Second attempt
            attempt2 = LessonAttempt.create_attempt(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                lesson_progress_id=test_lesson_progress.id
            )
            db_session.commit()

            assert attempt2.attempt_number == 2

    def test_attempt_repr(self, app, db_session, test_user, test_lesson_vocabulary, test_lesson_progress):
        """Тест __repr__ метода"""
        with app.app_context():
            attempt = LessonAttempt.create_attempt(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                lesson_progress_id=test_lesson_progress.id
            )
            db_session.commit()

            repr_str = repr(attempt)
            assert 'LessonAttempt' in repr_str
            assert str(test_user.id) in repr_str
            assert str(test_lesson_vocabulary.id) in repr_str
            assert str(attempt.attempt_number) in repr_str

    def test_complete_attempt(self, app, db_session, test_user, test_lesson_vocabulary, test_lesson_progress):
        """Тест завершения попытки"""
        with app.app_context():
            attempt = LessonAttempt.create_attempt(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                lesson_progress_id=test_lesson_progress.id
            )
            db_session.commit()

            # Complete the attempt
            mistakes = [{'question': 1, 'user_answer': 'wrong'}]
            attempt.complete(score=85.0, mistakes=mistakes, correct=17, total=20)
            db_session.commit()

            assert attempt.score == 85.0
            assert attempt.passed is True
            assert attempt.correct_answers == 17
            assert attempt.total_questions == 20
            assert attempt.mistakes == mistakes
            assert attempt.completed_at is not None
            assert attempt.time_spent_seconds is not None

    def test_complete_attempt_failed(self, app, db_session, test_user, test_lesson_vocabulary, test_lesson_progress):
        """Тест завершения неудачной попытки"""
        with app.app_context():
            attempt = LessonAttempt.create_attempt(
                user_id=test_user.id,
                lesson_id=test_lesson_vocabulary.id,
                lesson_progress_id=test_lesson_progress.id
            )
            db_session.commit()

            # Complete with failing score
            attempt.complete(score=50.0, correct=10, total=20)
            db_session.commit()

            assert attempt.score == 50.0
            assert attempt.passed is False