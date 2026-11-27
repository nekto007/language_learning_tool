"""Bounded read-only mixed queue recovery with the shared application and database fixtures."""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
import pytest
from sqlalchemy import event

from app.auth.models import User
from app.grammar_lab.answer_review import lab_revision
from app.grammar_lab.models import GrammarAttempt, GrammarExercise, GrammarTopic, UserGrammarExercise
from app.grammar_lab.routes import _resume_practice_session
from app.utils.db import db
from tests.api.test_native_full_integration import learner


@pytest.fixture
def mixed(app: Flask, authenticated_client: FlaskClient, test_user: User,
          monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    user = test_user
    topics = [GrammarTopic(slug='mixed-'+uuid4().hex, title='Mixed '+str(i), title_ru='Тема '+str(i),
                           level='A1', content={}) for i in range(3)]
    db.session.add_all(topics); db.session.flush()
    rows = [GrammarExercise(topic_id=topic.id, exercise_type='fill_blank',
                            content={'question': 'We ___ here.', 'correct_answer': 'are'}) for topic in topics]
    db.session.add_all(rows); db.session.commit()
    g.pop('csrf_token', None)
    token = authenticated_client.get('/csrf-token').get_json()['csrf_token']
    headers = {'X-CSRFToken': token}
    body = {'mode': 'resume', 'account_id': str(user.id), 'session_id': 'grammar_practice_'+str(user.id)+'_a1b2c3d4',
            'items': [{'id': row.id, 'revision': lab_revision(row)} for row in reversed(rows)]}
    yield {'app': app, 'user': user, 'rows': rows, 'client': authenticated_client, 'headers': headers, 'body': body}
    db.session.rollback(); g.pop('_login_user', None); g.pop('csrf_token', None)


def request_resume(mixed: dict[str, Any], body: Any = None, **kwargs: Any) -> Any:
    return mixed['client'].post('/grammar-lab/api/practice/session', headers=mixed['headers'],
                                json=mixed['body'] if body is None else body, **kwargs)


def test_resume_keeps_order_session_and_future_due_without_writes(mixed: Any) -> None:
    user = mixed['user']; row = mixed['rows'][0]
    future = datetime.now(UTC)+timedelta(days=9)
    progress = UserGrammarExercise(user_id=user.id, exercise_id=row.id)
    progress.state = 'review'; progress.next_review = future
    progress.interval = 9; progress.session_attempts = 2; progress.repetitions = 4
    db.session.add(progress); db.session.commit()
    before = deepcopy(progress.to_dict())
    response = request_resume(mixed)
    assert response.status_code == 200
    data = response.json
    assert data['account_id'] == str(user.id) and data['session_id'] == mixed['body']['session_id']
    assert [item['id'] for item in data['exercises']] == [item['id'] for item in mixed['body']['items']]
    assert data['total_exercises'] == 3 and len(data['exercise_revisions']) == 3
    assert all(item['topic_title'] and UUID(item['submission_id']).version == 4 for item in data['exercises'])
    assert all('correct_answer' not in item and 'alternatives' not in item for item in data['exercises'])
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert progress.to_dict() == before
    assert UserGrammarExercise.query.filter_by(user_id=user.id).count() == 1
    assert GrammarAttempt.query.filter_by(user_id=user.id).count() == 0
    second = request_resume(mixed).json
    assert second['exercises'][0]['submission_id'] != data['exercises'][0]['submission_id']


@pytest.mark.parametrize('change', ['retired', 'deleted', 'content', 'override'])
def test_changed_queue_is_rejected_as_a_whole(mixed: Any, change: str) -> None:
    row = mixed['rows'][1]
    if change == 'retired':
        row.content = {**row.content, 'guided_retired': True}
    elif change == 'deleted':
        db.session.delete(row)
    elif change == 'content':
        row.content = {**row.content, 'question': 'They ___ ready.'}
    else:
        from app.grammar_lab.answer_review import LAB_GRADER_VERSION
        row.answer_review_override = {'source_revision': lab_revision(row), 'grader_version': LAB_GRADER_VERSION,
                                      'patch': {'alternatives': ['ARE!']}}
    db.session.commit()
    response = request_resume(mixed)
    assert response.status_code == 409 and response.json['code'] == 'lesson_changed'
    assert 'exercises' not in response.json
    assert response.headers['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('mutation', ['empty', 'eleven', 'duplicate', 'bool', 'float', 'negative', 'huge',
                                     'revision', 'no_revision', 'extra_item', 'extra_create', 'session', 'mode'])
def test_resume_validates_a_bounded_exact_request(mixed: Any, mutation: str) -> None:
    body = deepcopy(mixed['body'])
    if mutation == 'empty': body['items'] = []
    elif mutation == 'eleven': body['items'] = [body['items'][0]]*11
    elif mutation == 'duplicate': body['items'][1] = deepcopy(body['items'][0])
    elif mutation in {'bool', 'float', 'negative', 'huge'}:
        body['items'][0]['id'] = {'bool': True, 'float': 1.5, 'negative': -1, 'huge': 2**100}[mutation]
    elif mutation == 'revision': body['items'][0]['revision'] = 'not-a-digest'
    elif mutation == 'no_revision': del body['items'][0]['revision']
    elif mutation == 'extra_item': body['items'][0]['answer'] = 'are'
    elif mutation == 'extra_create': body['count'] = 100
    elif mutation == 'session': body['session_id'] = 'x'*101
    else: body['mode'] = 'unknown'
    assert request_resume(mixed, body).status_code == 400


def test_resume_is_bound_to_cookie_actor_and_csrf(mixed: Any) -> None:
    other, _ = learner(mixed['app'])
    body = {**mixed['body'], 'account_id': str(other.id)}
    assert request_resume(mixed, body).status_code == 403
    anonymous = mixed['app'].test_client(); g.pop('_login_user', None)
    response = anonymous.post('/grammar-lab/api/practice/session', json=mixed['body'])
    assert response.status_code != 200
    g.pop('_login_user', None)
    bad_csrf = mixed['client'].post('/grammar-lab/api/practice/session', json=mixed['body'],
                                    headers={'X-CSRFToken': 'expired'})
    assert bad_csrf.status_code == 400


@pytest.mark.parametrize('size', [1, 10])
def test_resume_queries_only_requested_rows_in_one_select(mixed: Any, size: int) -> None:
    topic_id = mixed['rows'][0].topic_id
    rows = [GrammarExercise(topic_id=topic_id, exercise_type='fill_blank',
                            content={'question': 'They ___ here.', 'correct_answer': 'are'}) for _ in range(120)]
    db.session.add_all(rows); db.session.commit()
    body = {**mixed['body'], 'items': [{'id': row.id, 'revision': lab_revision(row)} for row in rows[:size]]}
    uid = mixed['user'].id
    statements = []
    def capture(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        statements.append(statement)
    db.session.expire_all()
    # Open the test fixture's savepoint before measuring queries from the resume handler.
    db.session.connection()
    event.listen(db.engine, 'before_cursor_execute', capture)
    try:
        result, status = _resume_practice_session(body, uid)
    finally:
        event.remove(db.engine, 'before_cursor_execute', capture)
    assert status == 200 and len(result['exercises']) == size
    assert len(statements) == 1 and statements[0].lstrip().upper().startswith('SELECT')
    assert ' IN (' in statements[0] and 'JOIN grammar_topics' in statements[0]


@pytest.mark.parametrize('kind', ['mixed', 'topic', 'empty', 'empty_topic'])
def test_web_get_assigns_fresh_submission_ids_and_keeps_empty_shell(mixed: Any, monkeypatch: Any, kind: str) -> None:
    from app.grammar_lab.routes import grammar_service
    rows = [] if kind.startswith('empty') else [row.to_dict(hide_answer=True) for row in mixed['rows']]
    result = {'session_id': mixed['body']['session_id'], 'exercises': rows, 'total_exercises': len(rows),
              'exercise_revisions': {row.id: lab_revision(row) for row in mixed['rows']}}
    path = '/grammar-lab/practice'
    if kind in {'topic', 'empty_topic'}:
        topic = mixed['rows'][0].topic
        result['topic'] = topic.to_dict()
        if kind == 'empty_topic':
            del result['exercises']; del result['total_exercises']; del result['exercise_revisions']
        monkeypatch.setattr(grammar_service, 'start_topic_practice', lambda *a, **k: deepcopy(result))
        path += '/topic/'+str(topic.id)
    else:
        monkeypatch.setattr(grammar_service, 'get_practice_session', lambda *a, **k: deepcopy(result))
    response = mixed['client'].get(path)
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, no-store'
    page = BeautifulSoup(response.data, 'html.parser')
    assert page.select_one('#start-btn') and page.select_one('#check-btn')
    assert page.select_one('script[src$="js/grammar/practice.js?v=20261127-book-example"]')
    inline = next(tag.string for tag in page.select('script') if tag.string and 'let exercises =' in tag.string)
    exercises = json.loads(inline.split('let exercises = ', 1)[1].split(';', 1)[0])
    assert len(exercises) == len(rows)
    assert all(UUID(item['submission_id']).version == 4 for item in exercises)
