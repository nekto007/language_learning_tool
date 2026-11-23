"""Final tests expose teaching help and answer feedback only after submission."""
from copy import deepcopy

import pytest

from tests.api.test_quiz_corrections import (
    course as _course, document, native_app as _native_app, submit, progress_and_attempts,
)


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def course(native_app, monkeypatch):
    case = _course.__wrapped__(native_app, monkeypatch)
    from app.utils.db import db
    case[2].type = "final_test"
    case[2].content = {
        "learning_goal": "Проверь формы to be самостоятельно.",
        "instruction": "Выбери правильный ответ.",
        "description": "PRIVATE_THEORY: use am with I.",
        "starter": {"goal": "Проверь себя.", "lines": [
            {"english": "PRIVATE_STARTER: I am here.", "russian": "Я здесь."}]},
        "learning_steps": [{"id": "forms", "title": "Forms", "body": "PRIVATE_STEP"}],
        "questions": [{"type": "multiple_choice", "question": "I ___ here.",
                       "question_ru": "PRIVATE_TRANSLATION: Я здесь.",
                       "options": ["am", "is"], "correct": 0,
                       "hint": "PRIVATE_HINT: use am", "explanation": "PRIVATE_EXPLANATION: I + am."}],
    }
    db.session.commit()
    return case


def test_final_document_has_no_theory_starter_hints_or_answer_key(course):
    lesson = document(course)
    assert lesson["passing_score"] == 75
    assert lesson["theory"] == []
    assert not lesson.get("learning_steps") and not lesson.get("introduction")
    assert not lesson["immediate_feedback"] and "quiz_phase" not in lesson
    assert lesson["learning_goal"] == "Проверь формы to be самостоятельно."
    assert lesson["instruction"] == "Выбери правильный ответ."
    assert "PRIVATE_" not in str(lesson)
    assert "correct" not in lesson["questions"][0]
    assert not lesson["questions"][0].get("theory_help")
    assert lesson["questions"][0]['translation'] is None


def test_final_description_cannot_reappear_as_instruction(course):
    from app.utils.db import db
    course[2].content = {k: v for k, v in course[2].content.items() if k != "instruction"}
    db.session.commit()
    assert "PRIVATE_" not in document(course)["instruction"]


def test_untyped_old_final_document_requires_a_fresh_independent_document(course):
    from app.api.native_lessons import _signer
    from app.curriculum.models import LessonAttempt
    opened = document(course)
    sealed = _signer().loads(opened['session_token'])
    sealed.pop('lesson_type')
    opened['session_token'] = _signer().dumps(sealed)
    rejected = submit(course, opened, {'0': '0'})
    assert rejected.status_code == 409 and rejected.json['error'] == 'lesson_changed'
    assert LessonAttempt.query.filter_by(user_id=course[0].id, lesson_id=course[2].id).count() == 0
    assert submit(course, document(course), {'0': '0'}).json['completed']


def test_final_check_never_returns_feedback_and_submission_enforces_attempt_cap(course):
    _, headers, model, client, _ = course
    first = document(course)
    checked = client.post(f"/api/native/lessons/{model.id}/check", headers=headers, json={
        "session_token": first["session_token"], "question_id": "0", "answer": "1"})
    assert checked.status_code == 404 and checked.json == {"error": "not_found", "success": False}
    from app.curriculum.models import LessonProgress, LessonAttempt
    assert LessonProgress.query.filter_by(user_id=course[0].id, lesson_id=model.id).first() is None
    assert LessonAttempt.query.filter_by(user_id=course[0].id, lesson_id=model.id).count() == 0
    for attempt in range(3):
        token = first if attempt == 0 else document(course)
        result = submit(course, token, {"0": "1"})
        assert result.status_code == 200 and result.json["score"] == 0
        assert not result.json["passed"] and not result.json.get("correction_pending")
        assert result.json["feedback"][0]["expected"] == "am"
    # A lost final response can still be replayed after consuming the cap.
    assert submit(course, token, {"0": "0"}).json == result.json
    saved = deepcopy(progress_and_attempts(course)[0].data)
    rejected = submit(course, document(course), {"0": "0"})
    assert rejected.status_code == 429 and rejected.json["error"] == "rate_limit_exceeded"
    progress, attempts = progress_and_attempts(course)
    assert progress.data == saved and progress.last_score == 0 and len(attempts) == 3


@pytest.mark.parametrize("path", ["/learn/{id}/?ui=legacy", "/curriculum/lesson/{id}/final_test?ui=legacy",
                                 "/curriculum/lesson/{id}?ui=legacy"])
def test_every_final_get_uses_safe_renderer_even_with_legacy_draft(course, path):
    from tests.api.test_web_objective_practice import cookie_client
    from app.curriculum.models import LessonProgress
    from app.utils.db import db
    client, lesson = cookie_client(course)
    saved = {"answers": [{"value": "is", "correct": False}], "correct_answers": 0}
    progress = LessonProgress(user_id=course[0].id, lesson_id=lesson.id, status="in_progress", data=saved)
    db.session.add(progress)
    db.session.commit()
    response = client.get(path.format(id=lesson.id), follow_redirects=True)
    assert response.status_code == 200
    assert "guided-practice.js" in response.text
    assert "finalTestData" not in response.text and "PRIVATE_" not in response.text
    assert progress.data == saved
    document = client.get(f"/curriculum/api/lesson/{lesson.id}/practice")
    assert document.status_code == 200, document.json
    assert "resume_answers" not in document.json["lesson"]
    assert "correct_answers" not in document.json["lesson"]


def test_legacy_draft_only_resumes_structurally_valid_input_and_never_verdicts(course) -> None:
    import json
    from types import SimpleNamespace as NS
    from app.curriculum.routes.guided_practice import _legacy_final_answers
    from app.api.native_lessons import _digest, _signer

    questions = [
        {"id": "0", "input": "choice", "options": [{"value": "0", "label": "am"}, {"value": "1", "label": "is"}]},
        {"id": "1", "input": "order", "options": [{"value": "1", "label": "am"}, {"value": "0", "label": "I"}, {"value": "2", "label": "here"}]},
        {"id": "2", "input": "match", "left_options": [{"value": "0", "label": "hi"}, {"value": "1", "label": "bye"}],
         "options": [{"value": "0", "label": "привет"}, {"value": "1", "label": "пока"}]},
        {"id": "3", "input": "text", "options": []},
        {"id": "4", "input": "text", "options": []},
    ]
    data = {"correct_answers": 999, "answers": [
        {"value": "is", "correct": True, "correct_answer": "PRIVATE_KEY"},
        {"value": "I am here", "correct": True},
        {"value": "display pairs", "pairs": [{"left": "hi", "right": "пока", "correct": True},
                                              {"left": "bye", "right": "привет", "correct": True}]},
        {"value": "My own answer", "correct": False}, {"correct_answer": "PRIVATE_KEY"}]}
    lesson = course[2]
    data['_native_legacy_draft_origin'] = _signer().dumps({
        'purpose': 'legacy_final_draft', 'user': course[0].id, 'lesson': lesson.id,
        'lesson_type': 'final_test', 'revision': _digest(lesson.content),
        'answers_digest': _digest(data['answers']),
    })
    progress = NS(status="in_progress", data=deepcopy(data), user_id=course[0].id)
    resumed = _legacy_final_answers(questions, progress, lesson=lesson)
    assert resumed["0"] == "1"
    assert json.loads(resumed["1"]) == ["0", "1", "2"]
    assert json.loads(resumed["2"]) == {"0": "1", "1": "0"}
    assert resumed["3"] == "My own answer" and "4" not in resumed
    assert "PRIVATE_KEY" not in str(resumed) and progress.data == data
    progress.status = "completed"
    assert _legacy_final_answers(questions, progress, lesson=lesson) == {}


@pytest.mark.parametrize('mismatch', [None, 'unsigned', 'user', 'lesson', 'lesson_type',
                                      'revision', 'purpose', 'answers_digest', 'changed_input'])
def test_final_resume_requires_signed_matching_context_and_exact_input(course, mismatch: str | None) -> None:
    from app.api.native_lessons import _digest, _signer, _version
    from app.curriculum.models import LessonProgress
    from app.utils.db import db
    from tests.api.test_web_objective_practice import cookie_client

    client, lesson = cookie_client(course)
    saved = {'answers': [{'value': 'is', 'correct': True, 'correct_answer': 'PRIVATE_KEY'}]}
    origin = {'purpose': 'legacy_final_draft', 'user': course[0].id, 'lesson': lesson.id,
              'lesson_type': 'final_test', 'revision': _digest(lesson.content),
              'answers_digest': _digest(saved['answers'])}
    if mismatch in ('user', 'lesson'):
        origin[mismatch] += 1000
    elif mismatch in ('lesson_type', 'revision', 'purpose', 'answers_digest'):
        origin[mismatch] = 'ordinary_context'
    saved['_native_legacy_draft_origin'] = origin if mismatch == 'unsigned' else _signer().dumps(origin)
    if mismatch == 'changed_input':
        saved['answers'][0]['value'] = 'am'
    progress = LessonProgress(user_id=course[0].id, lesson_id=lesson.id, status='in_progress', data=saved)
    db.session.add(progress)
    db.session.commit()
    before = deepcopy(progress.data)
    version = _version(progress)
    response = client.get(f'/curriculum/api/lesson/{lesson.id}/practice')
    assert response.status_code == 200
    if mismatch is None:
        assert response.json['lesson']['resume_answers'] == {'0': '1'}
    else:
        assert 'resume_answers' not in response.json['lesson']
    assert 'PRIVATE_KEY' not in str(response.json)
    db.session.refresh(progress)
    assert progress.data == before and _version(progress) == version


def test_ordinary_draft_never_seeds_final_and_private_input_archive_survives_repeats(course) -> None:
    import re
    from flask import g
    from app.api.native_lessons import _version
    from app.curriculum.models import LessonProgress
    from app.utils.db import db
    from tests.api.test_web_objective_practice import cookie_client

    lesson = course[2]
    lesson.type = 'reading'
    lesson.content = {'text': 'Synthetic task reference.', 'questions': [
        {'type': 'multiple_choice', 'question': 'I ___ here.', 'options': ['am', 'is'], 'correct': 0}]}
    db.session.commit()
    client, _ = cookie_client(course)
    g.pop('csrf_token', None)
    page = client.get(f'/learn/{lesson.id}/')
    csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text).group(1)
    headers = {'X-CSRFToken': csrf}
    saved = {'answers': [{'value': 'am', 'correct': True, 'correct_answer': 'PRIVATE_KEY',
                          'pairs': [{'left': 'my left', 'right': 'my right', 'correct': True}]}]}
    posted = client.post(f'/curriculum/api/lesson/{lesson.id}/progress', headers=headers,
                         json={'status': 'in_progress', 'data': saved})
    assert posted.status_code == 200, posted.get_json(silent=True)
    lesson.type = 'final_test'
    db.session.commit()
    progress = LessonProgress.query.filter_by(user_id=course[0].id, lesson_id=lesson.id).one()
    before = deepcopy(progress.data)
    version = _version(progress)
    opened = client.get(f'/curriculum/api/lesson/{lesson.id}/practice')
    assert opened.status_code == 200 and 'resume_answers' not in opened.json['lesson']
    db.session.refresh(progress)
    assert progress.data == before and _version(progress) == version
    assert '_native_legacy_draft' not in progress.data
    for token in [opened.json['lesson']['session_token'], None]:
        if token is None:
            fresh = client.get(f'/curriculum/api/lesson/{lesson.id}/practice')
            assert 'resume_answers' not in fresh.json['lesson'] and '_native_legacy' not in str(fresh.json)
            token = fresh.json['lesson']['session_token']
        result = client.post(f'/curriculum/api/lesson/{lesson.id}/practice/submit', headers=headers,
                             json={'session_token': token, 'answers': {'0': '0'}})
        assert result.status_code == 200 and result.json['completed']
        db.session.refresh(progress)
        assert progress.data['_native_legacy_draft'] == {'answers': {'0': {
            'value': 'am', 'pairs': [{'left': 'my left', 'right': 'my right'}]}}}
        assert 'PRIVATE_KEY' not in str(progress.data['_native_legacy_draft'])
        assert '_native_legacy' not in str(result.json)


def test_failed_final_attempt_write_rolls_back_progress_and_surfaces_failure(course):
    from sqlalchemy import event
    from app.curriculum.models import LessonProgress, LessonAttempt
    from app.curriculum.services.progress_service import ProgressService
    from app.utils.db import db

    def fail_attempt(*args):
        raise RuntimeError("Injected final attempt storage failure")

    event.listen(LessonAttempt, "before_insert", fail_attempt)
    try:
        with pytest.raises(RuntimeError, match="Injected final attempt storage failure"):
            ProgressService.update_progress_with_grading(course[0].id, course[2], {"score": 50})
        db.session.rollback()
        assert LessonProgress.query.filter_by(user_id=course[0].id, lesson_id=course[2].id).first() is None
        assert LessonAttempt.query.filter_by(user_id=course[0].id, lesson_id=course[2].id).count() == 0
    finally:
        event.remove(LessonAttempt, "before_insert", fail_attempt)


@pytest.mark.parametrize('transport', ['service', 'json', 'form'])
def test_retained_final_writers_preserve_archive_without_publishing_it(course, monkeypatch, transport: str) -> None:
    from app.curriculum.models import LessonProgress
    from app.curriculum.services.progress_service import ProgressService
    from app.utils.db import db
    from tests.api.test_native_owned_progress import cookie

    # These SQLite transport fixtures isolate unrelated PostgreSQL analytics.
    monkeypatch.setattr('app.achievements.services.process_lesson_completion', lambda **kw: None)

    saved = {'answers': [{'value': 'my own old input', 'correct': True, 'correct_answer': 'PRIVATE_KEY'}]}
    progress = LessonProgress(user_id=course[0].id, lesson_id=course[2].id, status='in_progress', data=saved)
    db.session.add(progress)
    db.session.commit()
    client, headers = cookie(course)
    for _ in range(2):
        if transport == 'service':
            result = {'score': 100, 'passed': True, 'correct_answers': 1, 'total_questions': 1}
            ProgressService.update_progress_with_grading(course[0].id, course[2], result)
            public = result
        elif transport == 'json':
            response = client.post(f'/curriculum/api/lesson/{course[2].id}/submit', headers=headers,
                                   json={'answers': {'0': '0'}})
            assert response.status_code == 200, response.json
            public = response.json
        else:
            response = client.post(f'/curriculum/lesson/{course[2].id}/final_test',
                                   headers={**headers, 'X-Requested-With': 'XMLHttpRequest'},
                                   data={'answer_0': 'am'})
            assert response.status_code == 200, response.json
            public = response.json
        db.session.refresh(progress)
        assert progress.data['_native_legacy_draft'] == {'answers': {'0': {'value': 'my own old input'}}}
        assert '_native_legacy' not in str(public) and 'PRIVATE_KEY' not in str(public)


@pytest.mark.parametrize('transport', ['service', 'native'])
def test_failed_final_archive_write_preserves_original_input_atomically(course, transport: str) -> None:
    from sqlalchemy import event
    from app.api.native_lessons import _version
    from app.curriculum.models import LessonProgress, LessonAttempt
    from app.curriculum.services.progress_service import ProgressService
    from app.utils.db import db

    saved = {'answers': [{'value': 'own original', 'correct': True, 'correct_answer': 'PRIVATE_KEY'}]}
    progress = LessonProgress(user_id=course[0].id, lesson_id=course[2].id, status='in_progress', data=saved)
    db.session.add(progress)
    db.session.commit()
    version = _version(progress)

    def fail_attempt(*args: object) -> None:
        raise RuntimeError('Injected archive/attempt write failure')

    event.listen(LessonAttempt, 'before_insert', fail_attempt)
    try:
        if transport == 'service':
            with pytest.raises(RuntimeError, match='Injected archive/attempt'):
                ProgressService.update_progress_with_grading(course[0].id, course[2], {'score': 100})
        else:
            response = submit(course, document(course), {'0': '0'})
            assert response.status_code == 500
        db.session.rollback()
        db.session.refresh(progress)
        assert progress.data == saved and _version(progress) == version
        assert LessonAttempt.query.filter_by(user_id=course[0].id, lesson_id=course[2].id).count() == 0
    finally:
        event.remove(LessonAttempt, 'before_insert', fail_attempt)
