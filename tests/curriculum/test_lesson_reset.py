"""Tests: единая reset-семантика кнопки «Повторить» (?reset=true)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.routes.lessons import maybe_reset_lesson_progress
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
    def test_resets_completed_progress(self, app, db_session, test_user, module_with_lessons):
        _, lesson = module_with_lessons
        progress = _complete(db_session, test_user.id, lesson)
        with app.test_request_context('/?reset=true'):
            assert maybe_reset_lesson_progress(progress) is True
        assert progress.status == 'in_progress'
        assert progress.score is None
        assert progress.data is None
        assert progress.completed_at is None

    def test_noop_without_param(self, app, db_session, test_user, module_with_lessons):
        _, lesson = module_with_lessons
        progress = _complete(db_session, test_user.id, lesson)
        with app.test_request_context('/'):
            assert maybe_reset_lesson_progress(progress) is False
        assert progress.status == 'completed'

    def test_noop_for_none_progress(self, app):
        with app.test_request_context('/?reset=true'):
            assert maybe_reset_lesson_progress(None) is False


@pytest.mark.smoke
class TestResetOverHttp:
    def test_learn_url_with_reset_clears_progress(
        self, app, client, db_session, test_user, module_with_lessons
    ):
        _, lesson = module_with_lessons
        progress = _complete(db_session, test_user.id, lesson)
        _login(client, test_user)
        resp = client.get(f'/learn/{lesson.id}/?reset=true', follow_redirects=True)
        assert resp.status_code == 200
        db_session.refresh(progress)
        assert progress.status == 'in_progress'
        assert progress.data is None

    def test_module_page_repeat_button_has_reset(
        self, app, client, db_session, test_user, module_with_lessons
    ):
        module, lesson = module_with_lessons
        _complete(db_session, test_user.id, lesson)
        _login(client, test_user)
        resp = client.get(f'/learn/{module.level.code.lower()}/module-{module.number}/')
        assert resp.status_code == 200
        assert f'/learn/{lesson.id}/?reset=true'.encode() in resp.data
