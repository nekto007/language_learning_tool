"""Read-only checks and stale credentials cannot mutate an independent round."""
from copy import deepcopy
import time

import pytest
from itsdangerous.timed import TimestampSigner

from tests.api.test_quiz_corrections import (
    course as _course, document, native_app as _native_app, submit, progress_and_attempts,
)


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def course(native_app, monkeypatch):
    return _course.__wrapped__(native_app, monkeypatch)


@pytest.mark.parametrize("phase", ["first", "correction"])
def test_six_hour_old_document_rejects_check_and_submit_without_writes(course, monkeypatch, phase):
    from app.curriculum.models import LessonProgress, LessonAttempt
    if phase == "correction":
        assert submit(course, document(course), {"0": "She go to school", "1": "1"}).status_code == 200
    progress = LessonProgress.query.filter_by(user_id=course[0].id, lesson_id=course[2].id).first()
    before = deepcopy(progress.data) if progress else None
    count = LessonAttempt.query.filter_by(user_id=course[0].id, lesson_id=course[2].id).count()
    with monkeypatch.context() as old_clock:
        old_clock.setattr(TimestampSigner, "get_timestamp", lambda self: int(time.time()) - 21601)
        expired = document(course)
    _, headers, model, client, _ = course
    checked = client.post(f"/api/native/lessons/{model.id}/check", headers=headers, json={
        "session_token": expired["session_token"], "question_id": "0", "answer": "She goes to school"})
    assert checked.status_code == 409 and checked.json["error"] == "lesson_changed"
    answers = {"0": "She goes to school"} if phase == "correction" else {"0": "She goes to school", "1": "1"}
    rejected = submit(course, expired, answers)
    assert rejected.status_code == 409 and rejected.json["error"] == "lesson_changed"
    progress = LessonProgress.query.filter_by(user_id=course[0].id, lesson_id=model.id).first()
    assert (progress.data if progress else None) == before
    assert LessonAttempt.query.filter_by(user_id=course[0].id, lesson_id=model.id).count() == count


def test_open_document_cannot_use_revoked_password_credentials(course):
    from app.curriculum.models import LessonProgress, LessonAttempt
    from app.utils.db import db
    opened = document(course)
    course[0].set_password("new-local-test-password-revokes-old-bearer")
    db.session.commit()
    response = submit(course, opened, {"0": "She goes to school", "1": "1"})
    assert response.status_code == 401
    assert LessonProgress.query.filter_by(user_id=course[0].id, lesson_id=course[2].id).first() is None
    assert LessonAttempt.query.filter_by(user_id=course[0].id, lesson_id=course[2].id).count() == 0


def test_completed_checks_never_replace_independent_answers_or_score(course):
    first = document(course)
    response = submit(course, first, {"0": "She go to school", "1": "1"})
    assert response.status_code == 200 and response.json["score"] == 50
    correction = document(course)
    before = deepcopy(progress_and_attempts(course)[0].data)
    _, headers, model, client, _ = course
    for level in range(4):
        checked = client.post(f"/api/native/lessons/{model.id}/check", headers=headers, json={
            "session_token": correction["session_token"], "question_id": "0",
            "answer": "She goes to school", "help_level": level})
        assert checked.status_code == 200 and checked.json["feedback"]["correct"]
        assert progress_and_attempts(course)[0].data == before
    progress, attempts = progress_and_attempts(course)
    assert progress.last_score == 50 and len(attempts) == 1
    assert progress.status == "in_progress"  # Only correction submit completes.


@pytest.mark.parametrize(('original_type', 'new_type'), [('grammar', 'final_test'), ('final_test', 'grammar')])
def test_retyping_same_content_invalidates_check_and_submit_tokens(course, original_type, new_type):
    from app.curriculum.models import LessonProgress, LessonAttempt
    from app.utils.db import db
    model = course[2]
    model.type = original_type
    model.content = {**model.content, 'questions': deepcopy(model.content['exercises'])}
    db.session.commit()
    ordinary = document(course)
    assert ordinary['immediate_feedback'] is (original_type == 'grammar')
    model.type = new_type
    db.session.commit()
    # Content bytes and progress stayed unchanged, but grading mode changed.
    checked = course[3].post(f'/api/native/lessons/{model.id}/check', headers=course[1], json={
        'session_token': ordinary['session_token'], 'question_id': '0', 'answer': 'She goes to school'})
    assert checked.status_code == 409 and checked.json['error'] == 'lesson_changed'
    response = submit(course, ordinary, {'0': 'She goes to school', '1': '1'})
    assert response.status_code == 409 and response.json['error'] == 'lesson_changed'
    assert LessonProgress.query.filter_by(user_id=course[0].id, lesson_id=model.id).first() is None
    assert LessonAttempt.query.filter_by(user_id=course[0].id, lesson_id=model.id).count() == 0
    final = document(course)
    assert final['passing_score'] == (75 if new_type == 'final_test' else 50)
    assert final['immediate_feedback'] is (new_type == 'grammar')
    assert submit(course, final, {'0': 'She goes to school', '1': '1'}).json['completed']


def test_retyping_same_content_invalidates_translation_review_before_external_call(course, monkeypatch):
    from app.utils.db import db
    model = course[2]
    model.content = {**model.content, 'mode': 'open', 'items': [
        {'russian': 'Она ходит в школу.', 'english': 'She goes to school.'}]}
    db.session.commit()
    opened = document(course)
    model.type = 'translation'
    db.session.commit()
    calls = []
    monkeypatch.setattr('app.curriculum.translation_review.review_item', lambda *a: calls.append(a))
    response = course[3].post(f'/api/native/lessons/{model.id}/review', headers=course[1], json={
        'session_token': opened['session_token'], 'index': 0, 'answer': 'She goes to school.'})
    assert response.status_code == 409 and response.json['error'] == 'lesson_changed'
    assert calls == []


@pytest.mark.parametrize('phase', ['first', 'correction'])
def test_legacy_untyped_ordinary_tokens_keep_active_drafts_usable(course, phase):
    from app.api.native_lessons import _signer
    first = document(course)
    if phase == 'correction':
        assert submit(course, first, {'0': 'She go to school', '1': '1'}).json['correction_pending']
    opened = first if phase == 'first' else document(course)
    sealed = _signer().loads(opened['session_token'])
    sealed.pop('lesson_type')
    opened['session_token'] = _signer().dumps(sealed)
    result = submit(course, opened, {'0': 'She goes to school', **({'1': '1'} if phase == 'first' else {})})
    assert result.status_code == 200 and result.json['completed'], result.json
    assert result.json['score'] == (100 if phase == 'first' else 50)
