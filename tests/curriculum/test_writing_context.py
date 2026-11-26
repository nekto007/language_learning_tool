"""A writing history entry uses the projection bound to the submitted opening."""

import json
import re
from typing import Any

import pytest
from bs4 import BeautifulSoup
from flask import g
from flask.testing import FlaskClient

from app.api.native_lessons import _signer
from app.auth.models import User
from app.curriculum.models import LessonProgress, UserWritingAttempt, save_writing_attempt
from app.utils import languagetool
from app.utils.db import db
from tests.api.test_course_receipt_expiry import effects, receipt, sign_in
from tests.api.test_native_quiz_disputes import _headers

A = {'prompt': 'Describe a train trip.', 'min_words': 5, 'checklist': ['Route', 'Arrival']}
B = {'prompt': 'Describe a family meal.', 'min_words': 5, 'checklist': ['Food', 'Company']}
ANSWER = 'We shared a meal in the garden.'


@pytest.fixture
def writing(receipt: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:  # noqa: F811
    monkeypatch.setattr(languagetool, 'check_text', lambda *_: None)
    lesson = receipt['lesson']
    lesson.type, lesson.title, lesson.content = 'writing_prompt', 'A train trip', A
    db.session.commit()
    return receipt


def opened(client: FlaskClient, lesson: int) -> str:
    g.pop('_login_user', None)
    response = client.get(f'/curriculum/lesson/{lesson}/writing-prompt')
    assert response.status_code == 200
    token = re.search(r'const WRITING_CONTEXT = ("[^"]+");', response.text)
    assert token
    return json.loads(token[1])


def stored(writing: dict[str, Any]) -> list[UserWritingAttempt]:
    return UserWritingAttempt.query.filter_by(
        user_id=writing['user'].id, lesson_id=writing['lesson'].id,
    ).order_by(UserWritingAttempt.id).all()


def cards(client: FlaskClient) -> list:
    g.pop('_login_user', None)
    response = client.get('/study/writing')
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser').select('.writing-history__item')


def test_web_opening_uses_one_revision_even_when_progress_initialization_commits(
    writing: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
) -> None:
    lesson, student, app = writing['lesson'], writing['user'], writing['app']
    client = app.test_client()
    headers = sign_in(client, app, student)
    commit = db.session.commit
    published = False

    def publish_after_progress_commit() -> None:
        nonlocal published
        creating_progress = any(isinstance(row, LessonProgress) for row in db.session.new)
        commit()
        if creating_progress and not published:
            published = True
            lesson.title, lesson.content = 'A family meal', B
            commit()

    monkeypatch.setattr(db.session, 'commit', publish_after_progress_commit)
    response = client.get(f'/curriculum/lesson/{lesson.id}/writing-prompt')
    assert response.status_code == 200 and published
    page = BeautifulSoup(response.data, 'html.parser')
    assert page.select_one('#prompt-text').text == B['prompt']
    assert page.select_one('.lsn-title').text == 'A family meal'
    match = re.search(r'const WRITING_CONTEXT = ("[^"]+");', response.text)
    assert match
    result = client.post(f'/curriculum/api/lesson/{lesson.id}/submit', headers=headers, json={
        'response_text': ANSWER, 'checked_items': B['checklist'], 'writing_context': json.loads(match[1]),
    })
    assert result.status_code == 200 and result.json['completed']
    attempt, = stored(writing)
    assert attempt.prompt_snapshot == {'title': 'A family meal', 'prompt': B['prompt'], 'translation': None}


def test_web_context_stale_malformed_foreign_and_legacy(
    writing: dict[str, Any], test_user: User,
) -> None:
    app, student, lesson = writing['app'], writing['user'], writing['lesson']
    old, fresh, outsider = (app.test_client() for _ in range(3))
    old_headers = sign_in(old, app, student)
    token_a = opened(old, lesson.id)
    lesson.title, lesson.content = 'A family meal', B
    db.session.commit()
    fresh_headers = sign_in(fresh, app, student)
    token_b = opened(fresh, lesson.id)
    assert token_a != token_b and opened(fresh, lesson.id) != token_b
    outsider_headers = sign_in(outsider, app, test_user)
    route = f'/curriculum/api/lesson/{lesson.id}/submit'
    data = {'response_text': ANSWER, 'checked_items': B['checklist']}
    before = effects(writing)
    for client, headers, token, status, error in (
        (old, old_headers, token_a, 409, 'lesson_changed'),
        (fresh, fresh_headers, token_b + 'broken', 400, 'invalid_writing_context'),
        (fresh, fresh_headers, None, 400, 'invalid_writing_context'),
        (outsider, outsider_headers, token_b, 403, 'access_denied'),
    ):
        g.pop('_login_user', None)
        response = client.post(route, headers=headers, json=data | {'writing_context': token})
        assert (response.status_code, response.json['error']) == (status, error)
    assert not stored(writing) and effects(writing) == before
    assert not cards(outsider)

    g.pop('_login_user', None)
    response = fresh.post(route, headers=fresh_headers, json=data | {'writing_context': token_b})
    assert response.status_code == 200 and response.json['completed']
    bound, = stored(writing)
    assert bound.prompt_snapshot == {'title': 'A family meal', 'prompt': B['prompt'], 'translation': None}
    original = (bound.id, bound.created_at, bound.response_text, bound.word_count)
    lesson.title, lesson.content = 'A walk', B | {'prompt': 'Describe a walk.'}
    db.session.commit()

    g.pop('_login_user', None)
    legacy = fresh.post(route, headers=fresh_headers, json=data)
    assert legacy.status_code == 200 and legacy.json['completed']
    assert len(stored(writing)) == 2 and stored(writing)[1].prompt_snapshot is None
    assert (bound.id, bound.created_at, bound.response_text, bound.word_count) == original
    legacy_card, bound_card = cards(fresh)
    assert legacy_card.select_one('.writing-history__prompt-source').text == 'Текущее условие урока'
    assert legacy_card.select_one('.writing-history__prompt').text == 'Describe a walk.'
    assert not bound_card.select_one('.writing-history__prompt-source')
    assert bound_card.select_one('.writing-history__lesson-title').text == 'A family meal'
    assert bound_card.select_one('.writing-history__prompt').text == B['prompt']
    assert not cards(outsider)


def test_bound_history_keeps_writing_when_reimport_changes_current_lesson_type(
    writing: dict[str, Any],
) -> None:
    app, student, lesson = writing['app'], writing['user'], writing['lesson']
    web = app.test_client()
    sign_in(web, app, student)
    snapshot = {'title': lesson.title, 'prompt': A['prompt'], 'translation': None}
    save_writing_attempt(student.id, lesson.id, 'A saved response about the train.', True, db, prompt_snapshot=snapshot)
    save_writing_attempt(student.id, lesson.id, 'A legacy response.', True, db)
    db.session.commit()
    assert len(cards(web)) == 2
    for lesson_type, content, expected in (
        ('quiz', {'questions': []}, 1),
        ('translation', {'russian': 'A different current exercise.'}, 2),
    ):
        lesson.type, lesson.content = lesson_type, content
        db.session.commit()
        assert len(cards(web)) == expected
        g.pop('_login_user', None)
        filtered = web.get('/study/writing?type=writing_prompt')
        assert filtered.status_code == 200
        card, = BeautifulSoup(filtered.data, 'html.parser').select('.writing-history__item')
        assert card.select_one('.writing-history__type-badge--writing_prompt')
        assert card.select_one('.writing-history__prompt').text == A['prompt']
        assert card.select_one('.writing-history__preview').text == 'A saved response about the train.'
        assert 'A legacy response.' not in filtered.text
    g.pop('_login_user', None)
    translated = web.get('/study/writing?type=translation')
    card, = BeautifulSoup(translated.data, 'html.parser').select('.writing-history__item')
    assert card.select_one('.writing-history__prompt').text == 'A different current exercise.'
    assert card.select_one('.writing-history__preview').text == 'A legacy response.'


@pytest.mark.parametrize('old_token', [False, True])
def test_native_bound_attempt_and_replay_after_edit(
    writing: dict[str, Any], old_token: bool,
) -> None:
    app, student, lesson = writing['app'], writing['user'], writing['lesson']
    lesson.content = A | {'prompt_ru': 'Напишите про поездку.'}
    db.session.commit()
    native, headers = app.test_client(), _headers(student)
    endpoint = f'/api/native/lessons/{lesson.id}'
    response = native.get(endpoint, headers=headers)
    assert response.status_code == 200
    document = response.json['lesson']
    question = document['questions'][0]
    proof = {'title': document['title'], 'prompt': question['prompt'], 'translation': question['translation']}
    assert proof['translation'] == lesson.content['prompt_ru']
    sealed = _signer().loads(document['session_token'])
    assert sealed['writing_prompt_snapshot'] == proof
    if old_token:
        del sealed['writing_prompt_snapshot']
    token = _signer().dumps(sealed) if old_token else document['session_token']
    body = {'session_token': token, 'answers': {'0': json.dumps(
        {'text': 'The train took us to the coast.', 'checked': A['checklist']},
    )}}
    submitted = native.post(endpoint + '/submit', headers=headers, json=body)
    assert submitted.status_code == 200 and submitted.json['completed']
    attempt, = stored(writing)
    assert attempt.prompt_snapshot == (None if old_token else proof)
    assert attempt.response_text == 'The train took us to the coast.'
    attempt_state = (attempt.id, attempt.created_at, attempt.word_count, attempt.prompt_snapshot)
    original = effects(writing)
    lesson.content = B
    db.session.commit()
    replay = native.post(endpoint + '/submit', headers=headers, json=body)
    assert replay.status_code == 200 and replay.json == submitted.json
    same, = stored(writing)
    assert (same.id, same.created_at, same.word_count, same.prompt_snapshot) == attempt_state
    assert effects(writing) == original

    web = app.test_client()
    sign_in(web, app, student)
    card, = cards(web)
    assert card.select_one('.writing-history__prompt').text == (B['prompt'] if old_token else proof['prompt'])
    assert bool(card.select_one('.writing-history__prompt-source')) == old_token
    assert bool(card.select_one('.writing-history__prompt[lang=ru]')) != old_token
