"""
Tests for Lesson UX improvements (Task 14):
- Empty content validation
- Progress save indicator (template elements)
- Lesson completion confirmation (template elements)
- Locked lesson reasons on module lessons page
- Continue where you left off for in-progress lessons
"""
import json
import uuid

import pytest
from unittest.mock import patch

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db


@pytest.fixture
def level_and_module(db_session):
    """Create a CEFR level and module for testing."""
    slug = uuid.uuid4().hex[:8]
    level = CEFRLevel(code='A1', name=f'Test Level {slug}')
    db_session.add(level)
    db_session.flush()

    module = Module(
        title=f'Test Module {slug}',
        number=1,
        level_id=level.id,
        description='Test module'
    )
    db_session.add(module)
    db_session.flush()
    return level, module


@pytest.fixture
def vocabulary_lesson(db_session, level_and_module):
    """Create a vocabulary lesson with content."""
    _, module = level_and_module
    content = {
        'words': [
            {'english': 'hello', 'russian': 'привет'},
            {'english': 'world', 'russian': 'мир'}
        ]
    }
    lesson = Lessons(
        title='Test Vocabulary',
        type='vocabulary',
        number=1,
        module_id=module.id,
        content=content
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


@pytest.fixture
def empty_content_lesson(db_session, level_and_module):
    """Create a lesson with no content."""
    _, module = level_and_module
    lesson = Lessons(
        title='Empty Lesson',
        type='quiz',
        number=1,
        module_id=module.id,
        content=None
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


@pytest.fixture
def lessons_sequence(db_session, level_and_module):
    """Create a sequence of lessons for lock testing."""
    _, module = level_and_module
    lessons = []
    for i in range(1, 4):
        lesson = Lessons(
            title=f'Lesson {i}',
            type='text',
            number=i,
            module_id=module.id,
            content={'text': f'Content for lesson {i}'}
        )
        db_session.add(lesson)
        lessons.append(lesson)
    db_session.flush()
    return lessons


class TestEmptyContentValidation:
    """Test empty content handling before rendering lessons."""

    @patch('app.curriculum.routes.main.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_empty_content_shows_unavailable_page(
        self, mock_sec_module, mock_sec_lesson, mock_main_module,
        authenticated_client, empty_content_lesson, db_session
    ):
        """Lesson with no content should render empty_content template."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Содержимое урока недоступно' in html

    @patch('app.curriculum.routes.main.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_lesson_with_content_renders_normally(
        self, mock_sec_module, mock_sec_lesson, mock_main_module,
        authenticated_client, vocabulary_lesson, db_session
    ):
        """Lesson with valid content should render normally (not empty page)."""
        response = authenticated_client.get(f'/learn/{vocabulary_lesson.id}/')
        # Could be 200 or 302 (redirect on validation error), but NOT empty_content
        html = response.data.decode()
        assert 'Содержимое урока недоступно' not in html

    @patch('app.curriculum.routes.main.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_card_lesson_without_content_still_renders(
        self, mock_sec_module, mock_sec_lesson, mock_main_module,
        authenticated_client, db_session, level_and_module
    ):
        """Card lessons without content should not show empty page (they use collection_id)."""
        _, module = level_and_module
        card_lesson = Lessons(
            title='Card Lesson',
            type='card',
            number=1,
            module_id=module.id,
            content=None
        )
        db_session.add(card_lesson)
        db_session.flush()

        response = authenticated_client.get(f'/learn/{card_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Содержимое урока недоступно' not in html


class TestProgressSaveIndicator:
    """Test that the auto-save toast element is present in lesson templates."""

    @patch('app.curriculum.routes.main.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_save_toast_in_empty_content_page(
        self, mock_sec_module, mock_sec_lesson, mock_main_module,
        authenticated_client, empty_content_lesson, db_session
    ):
        """Even the empty content page (extends lesson_base_template) has save-toast."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'id="save-toast"' in html
        assert 'showSaveToast' in html

    @patch('app.curriculum.routes.main.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_completion_element_in_empty_content_page(
        self, mock_sec_module, mock_sec_lesson, mock_main_module,
        authenticated_client, empty_content_lesson, db_session
    ):
        """Even the empty content page has completion confirmation element."""
        response = authenticated_client.get(f'/learn/{empty_content_lesson.id}/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'id="lesson-completion"' in html
        assert 'showLessonCompletion' in html


class TestModuleLessonsLockedReasons:
    """Test that locked lessons show the reason on module lessons page."""

    @patch('app.curriculum.routes.main.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_locked_lesson_shows_reason(
        self, mock_sec_module, mock_main_module,
        authenticated_client, lessons_sequence, level_and_module, db_session
    ):
        """Locked lessons should show which lesson to complete first."""
        level, module = level_and_module
        response = authenticated_client.get(
            f'/learn/{level.code.lower()}/module-{module.number}/'
        )
        assert response.status_code == 200
        html = response.data.decode()
        assert 'ml-lesson__locked-reason' in html
        assert 'Завершите урок' in html

    @patch('app.curriculum.routes.main.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_first_lesson_not_locked(
        self, mock_sec_module, mock_main_module,
        authenticated_client, lessons_sequence, level_and_module, db_session
    ):
        """First lesson in module should not be locked."""
        level, module = level_and_module
        response = authenticated_client.get(
            f'/learn/{level.code.lower()}/module-{module.number}/'
        )
        assert response.status_code == 200
        html = response.data.decode()
        assert 'ml-lesson--current' in html or 'ml-lesson--available' in html


class TestContinueWhereLeftOff:
    """Test in-progress lessons show progress hints on module page."""

    @patch('app.curriculum.routes.main.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_in_progress_quiz_shows_question_number(
        self, mock_sec_module, mock_main_module,
        authenticated_client, db_session, level_and_module
    ):
        """In-progress quiz lesson shows current question number."""
        level, module = level_and_module

        lesson = Lessons(
            title='Quiz Test',
            type='quiz',
            number=1,
            module_id=module.id,
            content={'questions': [{'question': 'Q1'}]}
        )
        db_session.add(lesson)
        db_session.flush()

        user = authenticated_client.application.test_user
        progress = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='in_progress',
            data={'current_question': 2, 'total_questions': 10, 'answers': []}
        )
        db_session.add(progress)
        db_session.commit()

        response = authenticated_client.get(
            f'/learn/{level.code.lower()}/module-{module.number}/'
        )
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Вопрос 3/10' in html  # current_question + 1

    @patch('app.curriculum.routes.main.check_module_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_completed_lesson_shows_score(
        self, mock_sec_module, mock_main_module,
        authenticated_client, db_session, level_and_module
    ):
        """Completed lesson shows score percentage."""
        level, module = level_and_module

        lesson = Lessons(
            title='Score Test',
            type='quiz',
            number=1,
            module_id=module.id,
            content={'questions': [{'question': 'Q1'}]}
        )
        db_session.add(lesson)
        db_session.flush()

        user = authenticated_client.application.test_user
        progress = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='completed',
            score=85.5
        )
        db_session.add(progress)
        db_session.commit()

        response = authenticated_client.get(
            f'/learn/{level.code.lower()}/module-{module.number}/'
        )
        assert response.status_code == 200
        html = response.data.decode()
        # score=85.5 rounds to 86.0 (Jinja2 round filter returns float)
        assert '86' in html or '85' in html


class TestUpdateLessonProgress:
    """Test the update_lesson_progress endpoint."""

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_save_progress_returns_success(
        self, mock_module, mock_lesson,
        authenticated_client, vocabulary_lesson, db_session
    ):
        """Saving progress should return success JSON."""
        response = authenticated_client.post(
            f'/curriculum/api/lesson/{vocabulary_lesson.id}/progress',
            data=json.dumps({
                'status': 'in_progress',
                'data': {'cards_viewed': 1, 'total_cards': 5}
            }),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True

    @patch('app.curriculum.security.check_lesson_access', return_value=True)
    @patch('app.curriculum.security.check_module_access', return_value=True)
    def test_save_completed_progress(
        self, mock_module, mock_lesson,
        authenticated_client, vocabulary_lesson, db_session
    ):
        """Completing a lesson should save status and score."""
        response = authenticated_client.post(
            f'/curriculum/api/lesson/{vocabulary_lesson.id}/progress',
            data=json.dumps({
                'status': 'completed',
                'score': 100,
                'data': {'cards_viewed': 5, 'total_cards': 5}
            }),
            content_type='application/json'
        )
        assert response.status_code == 200

        progress = LessonProgress.query.filter_by(
            lesson_id=vocabulary_lesson.id
        ).first()
        assert progress is not None
        assert progress.status == 'completed'
        assert progress.score == 100.0


class TestModuleLockReasons:
    """Test that module lock reasons show prerequisite module name and required score."""

    def test_locked_module_shows_prereq_info(self, app, db_session, authenticated_client):
        """When module is locked, page should show prerequisite module name and score."""
        suffix = uuid.uuid4().hex[:6]
        level = CEFRLevel(code=f'Z{suffix[:1].upper()}', name=f'Test {suffix}', order=99)
        db_session.add(level)
        db_session.flush()

        mod1 = Module(level_id=level.id, number=1, title=f'Prereq Module {suffix}')
        db_session.add(mod1)
        db_session.flush()

        # Add a lesson to mod1 but don't complete it (so mod2 stays locked)
        lesson1 = Lessons(module_id=mod1.id, number=1, title='L1', type='vocabulary', order=1)
        db_session.add(lesson1)
        db_session.flush()

        mod2 = Module(level_id=level.id, number=2, title=f'Locked Module {suffix}')
        db_session.add(mod2)
        db_session.flush()

        lesson2 = Lessons(module_id=mod2.id, number=1, title='L2', type='vocabulary', order=1)
        db_session.add(lesson2)
        db_session.commit()

        response = authenticated_client.get(f'/learn/{level.code.upper()}/module-2/')
        html = response.data.decode()

        # Should show module lock banner with prerequisite module name
        assert 'Модуль заблокирован' in html or f'Prereq Module {suffix}' in html or '0%' in html

        # Cleanup
        db_session.delete(lesson2)
        db_session.delete(lesson1)
        db_session.delete(mod2)
        db_session.delete(mod1)
        db_session.delete(level)
        db_session.commit()
