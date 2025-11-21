"""
Tests for URL helpers
Тесты вспомогательных функций для URL
"""
import pytest
from app.curriculum.url_helpers import get_beautiful_lesson_url


class TestUrlHelpers:
    """Тесты вспомогательных функций URL"""

    def test_get_beautiful_lesson_url(self, app, db_session, test_lesson_vocabulary):
        """Тест генерации красивого URL для урока"""
        with app.app_context():
            url = get_beautiful_lesson_url(test_lesson_vocabulary)
            assert url == f'/learn/{test_lesson_vocabulary.id}/'
            assert url.startswith('/learn/')
            assert url.endswith('/')

    def test_get_beautiful_lesson_url_with_different_id(self, app, db_session, test_module):
        """Тест генерации URL для урока с другим ID"""
        with app.app_context():
            from app.curriculum.models import Lessons

            # Create lesson with specific ID
            lesson = Lessons(
                module_id=test_module.id,
                number=999,
                type='vocabulary',
                title='Test Lesson',
                content={'words': []},
                order=1
            )
            db_session.add(lesson)
            db_session.commit()

            url = get_beautiful_lesson_url(lesson)
            assert url == f'/learn/{lesson.id}/'
            assert str(lesson.id) in url
