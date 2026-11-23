"""Late legacy submissions preserve graded ledgers; intentional repeats still work."""
from copy import deepcopy
import json
import re

import pytest

from tests.api.test_quiz_corrections import (
    course as _course, document, native_app as _native_app, submit, progress_and_attempts,
)


@pytest.fixture(scope='module')
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


@pytest.fixture
def course(native_app, monkeypatch):
    return _course.__wrapped__(native_app, monkeypatch)


def complete_correction(course):
    first = document(course)
    assert submit(course, first, {'0': 'She go to school', '1': '1'}).json['score'] == 50
    assert submit(course, document(course), {'0': 'She goes to school'}).json['completed']


@pytest.mark.parametrize('writer', ['grading', 'complete', 'upsert'])
def test_late_legacy_writer_preserves_completed_first_state_and_fresh_repeat_works(course, writer):
    from app.curriculum.services.progress_service import ProgressService
    from app.curriculum.service import complete_lesson
    from app.utils.db import db
    complete_correction(course)
    before = deepcopy(progress_and_attempts(course)[0].data)
    with pytest.raises(ValueError, match='versioned_submission_required'):
        if writer == 'grading':
            ProgressService.update_progress_with_grading(course[0].id, course[2], {'score': 100})
        elif writer == 'complete':
            complete_lesson(course[0].id, course[2].id, 100)
        else:
            ProgressService.create_or_update_progress(course[0].id, course[2].id, 'completed', 100, {})
    db.session.rollback()
    progress, attempts = progress_and_attempts(course)
    assert progress.status == 'completed' and progress.last_score == 50 and progress.data == before
    assert len(attempts) == 1
    repeat = submit(course, document(course), {'0': 'She goes to school', '1': '1'})
    assert repeat.status_code == 200 and repeat.json['completed'] and repeat.json['score'] == 100
    assert len(progress_and_attempts(course)[1]) == 2


def cookie(course):
    from flask import g
    from tests.api.test_web_objective_practice import cookie_client
    client, lesson = cookie_client(course)
    g.pop('csrf_token', None)
    page = client.get(f'/learn/{lesson.id}/', follow_redirects=True)
    csrf = re.search(r'<meta name="csrf-token" content="([^"]+)"', page.text).group(1)
    return client, {'X-CSRFToken': csrf}


def test_late_legacy_http_submit_returns_conflict_without_touching_native_receipt(course):
    complete_correction(course)
    before = deepcopy(progress_and_attempts(course)[0].data)
    client, headers = cookie(course)
    response = client.post(f'/curriculum/api/lesson/{course[2].id}/submit', headers=headers,
                           json={'answers': {'0': 'She goes to school', '1': '1'}})
    assert response.status_code == 409 and response.json['error'] == 'versioned_submission_required'
    progress, attempts = progress_and_attempts(course)
    assert progress.data == before and progress.status == 'completed' and progress.last_score == 50
    assert len(attempts) == 1


def test_completed_native_writing_allows_intentional_legacy_web_practice_repeat(course, monkeypatch):
    from app.utils.db import db
    lesson = course[2]
    lesson.type = 'writing_prompt'
    lesson.content = {'prompt': 'Introduce yourself.', 'min_words': 1, 'min_sentences': 1,
                      'checklist': ['Name', 'Place'], 'min_checklist': 2}
    db.session.commit()
    monkeypatch.setattr('app.utils.languagetool.check_text', lambda *a, **kw: None)
    first = submit(course, document(course), {'0': json.dumps({
        'text': 'Hello from the fixture.', 'checked': ['Name', 'Place']})})
    assert first.status_code == 200 and first.json['completed']
    client, headers = cookie(course)
    repeated = client.post(f'/curriculum/api/lesson/{lesson.id}/submit', headers=headers, json={
        'response_text': 'A second intentional fixture practice.', 'checked_items': ['Name', 'Place']})
    assert repeated.status_code == 200 and repeated.json['completed'], repeated.json


@pytest.mark.parametrize('completed_round', ['first', 'correction', 'final'])
def test_ignored_snapshot_keeps_fresh_repeat_valid_and_has_no_completion_effects(
        course, monkeypatch, completed_round: str) -> None:
    from app.api.native_lessons import _version
    from app.utils.db import db

    if completed_round == 'correction':
        complete_correction(course)
    elif completed_round == 'final':
        course[2].type = 'final_test'
        course[2].content = {'questions': [{'type': 'multiple_choice', 'question': 'I ___ here.',
                                          'options': ['am', 'is'], 'correct': 0}]}
        db.session.commit()
        assert submit(course, document(course), {'0': '0'}).json['completed']
    else:
        assert submit(course, document(course), {'0': 'She goes to school', '1': '1'}).json['completed']
    repeat = document(course)
    client, headers = cookie(course)
    progress, _attempts = progress_and_attempts(course)
    before = deepcopy(progress.data)
    version = _version(progress)
    effects = []
    monkeypatch.setattr('app.daily_plan.linear.xp.maybe_award_curriculum_xp',
                        lambda *a, **kw: effects.append('xp'))
    monkeypatch.setattr('app.achievements.services.process_lesson_completion',
                        lambda *a, **kw: effects.append('completion'))
    response = client.post(f'/curriculum/api/lesson/{course[2].id}/progress', headers=headers,
                           json={'status': 'in_progress', 'data': {'answers': {'0': 'stale input'}}})
    assert response.status_code == 200 and response.json['progress']['status'] == 'completed'
    db.session.refresh(progress)
    assert progress.data == before and _version(progress) == version and effects == []
    if completed_round == 'final':
        checked = submit(course, repeat, {'0': '0'})
        assert checked.status_code == 200 and checked.json['completed']
    else:
        checked = client.post(f'/api/native/lessons/{course[2].id}/check', headers=course[1], json={
            'session_token': repeat['session_token'], 'question_id': '0', 'answer': 'She goes to school'})
        assert checked.status_code == 200 and checked.json['feedback']['correct']
