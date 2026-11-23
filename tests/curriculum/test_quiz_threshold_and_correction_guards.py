"""Threshold writes and legacy-submit protection on a disposable SQLite DB."""
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask import g
from flask_login import login_user

from tests.api.test_account_deletion import native_app as _native_app
from tests.api.test_native_full_integration import learner


@pytest.fixture(scope='module')
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def material(native_app):
    from app.curriculum.models import CEFRLevel, Lessons, Module
    from app.utils.db import db

    user, _ = learner(native_app)
    user.onboarding_completed = True
    level = CEFRLevel(code='T' + uuid4().hex[:7], name='Test', order=1)
    db.session.add(level)
    db.session.flush()
    module = Module(level_id=level.id, number=1, title='Module', raw_content={})
    db.session.add(module)
    db.session.flush()
    questions = [dict(type='fill_blank', question='She ___ here.', correct_answer='is')] * 2
    lesson = Lessons(module_id=module.id, number=1, order=0, type='quiz', title='Quiz',
                     content={'questions': questions, 'passing_score_percent': 80})
    db.session.add(lesson)
    db.session.commit()
    return SimpleNamespace(user=user, lesson=lesson)


def progress_for(material, *, score=50, pending=False):
    from app.curriculum.models import LessonProgress
    from app.utils.db import db

    data = {'score': score, 'feedback': {'0': {'status': 'incorrect'}}}
    if pending:
        data['quiz_correction'] = {'version': 1, 'status': 'pending', 'attempt_id': uuid4().hex,
                                   'revision': 'a' * 64, 'first_score': score,
                                   'first_passed': score >= 50, 'pending_ids': ['0']}
    progress = LessonProgress(user_id=material.user.id, lesson_id=material.lesson.id,
                              status='in_progress', score=score, last_score=score, best_score=score,
                              data=data, started_at=datetime.now(UTC), last_activity=datetime.now(UTC))
    db.session.add(progress)
    db.session.commit()
    return progress


@pytest.mark.parametrize('kind,score,override,expected', [
    ('quiz', 50, 80, 'completed'), ('grammar', 50, 80, 'completed'),
    ('final_test', 74, 70, 'in_progress'), ('final_test', 75, 80, 'completed'),
    ('translation', 40, 40, 'completed'),
])
def test_recovery_uses_policy_and_keeps_custom_nonquiz_thresholds(native_app, material, kind, score, override, expected):
    from app.curriculum.recovery import reconcile_stuck_lesson_progress
    from app.utils.db import db

    material.lesson.type = kind
    material.lesson.content = {'passing_score_percent': override}
    if kind == 'translation':
        material.lesson.content = {**material.lesson.content, 'mode':'open'}
    progress = progress_for(material, score=score)
    reconcile_stuck_lesson_progress(db.session)
    db.session.refresh(progress)
    assert progress.status == expected


def test_recovery_never_uses_best_score_to_bypass_pending_correction(native_app, material):
    from app.curriculum.models import LessonAttempt
    from app.curriculum.recovery import reconcile_stuck_lesson_progress
    from app.utils.db import db

    progress = progress_for(material, score=100, pending=True)
    attempt = LessonAttempt(user_id=material.user.id, lesson_id=material.lesson.id,
                            lesson_progress_id=progress.id, attempt_number=1, score=100,
                            passed=True, started_at=datetime.now(UTC), completed_at=datetime.now(UTC))
    db.session.add(attempt)
    db.session.commit()
    saved = deepcopy(progress.data)
    reconcile_stuck_lesson_progress(db.session)
    db.session.refresh(progress)
    assert progress.status == 'in_progress'
    assert progress.data == saved


@pytest.mark.parametrize('entrypoint', ['grading_service', 'complete_lesson'])
def test_legacy_services_refuse_to_overwrite_pending_before_any_write(native_app, material, entrypoint):
    from app.curriculum.models import LessonAttempt
    from app.curriculum.service import complete_lesson
    from app.curriculum.services.progress_service import ProgressService
    from app.utils.db import db

    progress = progress_for(material, pending=True)
    before = deepcopy(progress.data), progress.score, progress.last_score, progress.best_score
    count = LessonAttempt.query.filter_by(user_id=material.user.id).count()
    with pytest.raises(ValueError, match='correction_required'):
        if entrypoint == 'grading_service':
            ProgressService.update_progress_with_grading(material.user.id, material.lesson, {'score': 100}, 50)
        else:
            complete_lesson(material.user.id, material.lesson.id, 100)
    db.session.refresh(progress)
    assert (progress.data, progress.score, progress.last_score, progress.best_score) == before
    assert progress.status == 'in_progress'
    assert LessonAttempt.query.filter_by(user_id=material.user.id).count() == count


@pytest.mark.parametrize('renderer', ['render_grammar_lesson', 'render_quiz_lesson'])
def test_browser_submit_returns_explicit_409_and_keeps_pending(native_app, material, renderer):
    import app.curriculum.routes.grammar_quiz_lessons as routes
    from app.utils.db import db

    if renderer == 'render_grammar_lesson':
        material.lesson.type = 'grammar'
        material.lesson.content = {'title': 'To be', 'content': 'Use is with she.',
                                  'exercises': [{'type': 'fill_blank', 'question': 'She ___ here.',
                                                 'correct_answer': 'is'}]}
    progress = progress_for(material, pending=True)
    saved = deepcopy(progress.data)
    with native_app.test_request_context('/curriculum/test', method='POST',
                                         data={'answer_0': 'is'},
                                         headers={'X-Requested-With': 'XMLHttpRequest'}):
        g.pop('_login_user', None)
        login_user(material.user)
        response, status = getattr(routes, renderer)(material.lesson)
    assert status == 409
    assert response.json['error'] == 'correction_required'
    db.session.refresh(progress)
    assert progress.data == saved and progress.status == 'in_progress'


def test_final_test_never_enters_pending_web_guard(native_app):
    from app.curriculum.routes.grammar_quiz_lessons import _pending_correction_response

    progress = SimpleNamespace(status='in_progress', data={'quiz_correction': {
        'version': 1, 'status': 'pending', 'attempt_id': 'old-malformed-flow'}})
    with native_app.test_request_context('/curriculum/test', method='POST'):
        assert _pending_correction_response(SimpleNamespace(type='final_test'), progress) is None


def test_browser_legacy_quiz_uses_50_despite_authored_80(native_app, material):
    from app.curriculum.routes.grammar_quiz_lessons import render_quiz_lesson
    from app.curriculum.models import LessonProgress

    with native_app.test_request_context('/curriculum/test', method='POST',
                                         data={'answer_0': 'IS!', 'answer_1': 'wrong'},
                                         headers={'X-Requested-With': 'XMLHttpRequest'}):
        g.pop('_login_user', None)
        login_user(material.user)
        response = render_quiz_lesson(material.lesson)
    assert response.status_code == 200
    assert response.json['passing_score'] == 50 and response.json['passed']
    progress = LessonProgress.query.filter_by(user_id=material.user.id, lesson_id=material.lesson.id).one()
    assert progress.status == 'completed' and progress.last_score == 50


def test_browser_autosave_cannot_erase_pending_correction(native_app, material):
    from app.curriculum.routes.lessons import update_lesson_progress
    from app.utils.db import db

    progress = progress_for(material, pending=True)
    saved = deepcopy(progress.data)
    with native_app.test_request_context('/curriculum/test/progress', method='POST',
                                         json={'status': 'in_progress', 'data': {'answers': {}}}):
        g.pop('_login_user', None)
        login_user(material.user)
        response, status = update_lesson_progress.__wrapped__.__wrapped__(material.lesson.id)
    assert status == 409 and response.json['error'] == 'correction_required'
    db.session.refresh(progress)
    assert progress.data == saved and progress.status == 'in_progress'


@pytest.mark.parametrize('kind,score,stale_threshold,expected', [
    ('quiz', 50, 80, 'completed'), ('grammar', 50, 70, 'completed'),
    ('final_test', 74, 70, 'in_progress'), ('final_test', 75, 80, 'completed'),
    ('quiz', 60, None, 'completed'), ('final_test', 70, None, 'in_progress'),
    ('final_test', 80, None, 'completed'),
])
def test_progress_service_cannot_reintroduce_stale_quiz_threshold(native_app, material, kind, score, stale_threshold, expected):
    from app.curriculum.services.progress_service import ProgressService

    material.lesson.type = kind
    kwargs = {'passing_score': stale_threshold} if stale_threshold is not None else {}
    progress, _ = ProgressService.update_progress_with_grading(
        material.user.id, material.lesson, {'score': score}, **kwargs)
    assert progress.status == expected
    assert progress.last_score == score
