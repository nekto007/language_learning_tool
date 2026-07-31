"""Tests: повтор урока не стирает завершение и лучший результат."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from flask import session

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.routes.lessons import (
    clear_lesson_retry,
    maybe_reset_lesson_progress,
    retry_display_progress,
)
from tests.conftest import unique_level_code


@pytest.fixture
def module_with_lessons(db_session):
    level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id, number=1, title='M', description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    vocab = Lessons(
        module_id=module.id, number=1, title='Vocab', type='vocabulary',
        content={'words': []},
    )
    db_session.add(vocab)
    db_session.commit()
    return module, vocab


def _complete(db_session, user_id, lesson, data=None):
    progress = LessonProgress(
        user_id=user_id, lesson_id=lesson.id, status='completed', score=85,
        completed_at=datetime.now(timezone.utc),
        data=data or {'something': True},
    )
    db_session.add(progress)
    db_session.commit()
    return progress


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


@pytest.mark.smoke
class TestMaybeResetHelper:
    def test_retry_keeps_completed_progress_and_renders_fresh_view(
        self, app, db_session, test_user, module_with_lessons
    ):
        _, lesson = module_with_lessons
        progress = _complete(db_session, test_user.id, lesson)
        with app.test_request_context('/?retry=true'):
            assert maybe_reset_lesson_progress(progress) is True
            display = retry_display_progress(progress)
        assert progress.status == 'completed'
        assert progress.score == 85
        assert progress.data == {'something': True}
        assert progress.completed_at is not None
        assert display.status == 'in_progress'
        assert display.score is None
        assert display.data is None

    def test_retry_session_persists_until_submission(self, app, db_session, test_user, module_with_lessons):
        _, lesson = module_with_lessons
        progress = _complete(db_session, test_user.id, lesson)

        with app.test_request_context('/'):
            session[f'curriculum_lesson_retry_{lesson.id}'] = True
            assert retry_display_progress(progress).status == 'in_progress'
            clear_lesson_retry(lesson.id)
            assert retry_display_progress(progress) is progress

    def test_score_records_best_and_last_attempt_separately(
        self, db_session, test_user, module_with_lessons
    ):
        _, lesson = module_with_lessons
        progress = LessonProgress(
            user_id=test_user.id,
            lesson_id=lesson.id,
            status='completed',
            score=85.5,
        )
        db_session.add(progress)
        db_session.commit()
        assert progress.best_score == 85.5
        assert progress.last_score == 85.5

        progress.record_score(72.25)
        db_session.commit()
        assert progress.score == 85.5
        assert progress.best_score == 85.5
        assert progress.last_score == 72.25

    def test_noop_without_param(self, app, db_session, test_user, module_with_lessons):
        _, lesson = module_with_lessons
        progress = _complete(db_session, test_user.id, lesson)
        with app.test_request_context('/'):
            assert maybe_reset_lesson_progress(progress) is False
        assert progress.status == 'completed'

    def test_noop_for_none_progress(self, app):
        with app.test_request_context('/?retry=true'):
            assert maybe_reset_lesson_progress(None) is False


@pytest.mark.smoke
class TestResetOverHttp:
    def test_learn_url_with_retry_keeps_completed_progress(
        self, app, client, db_session, test_user, module_with_lessons
    ):
        _, lesson = module_with_lessons
        progress = _complete(db_session, test_user.id, lesson)
        _login(client, test_user)
        resp = client.get(f'/learn/{lesson.id}/?retry=true', follow_redirects=True)
        assert resp.status_code == 200
        db_session.refresh(progress)
        assert progress.status == 'completed'
        assert progress.score == 85
        assert progress.data == {'something': True}

    def test_module_page_repeat_button_uses_non_destructive_retry(
        self, app, client, db_session, test_user, module_with_lessons
    ):
        module, lesson = module_with_lessons
        _complete(db_session, test_user.id, lesson)
        _login(client, test_user)
        resp = client.get(f'/learn/{module.level.code.lower()}/module-{module.number}/')
        assert resp.status_code == 200
        assert f'/learn/{lesson.id}/?retry=true'.encode() in resp.data
