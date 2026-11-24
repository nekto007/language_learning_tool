"""Expired course tokens can read their own committed receipt, never grade again."""

from copy import deepcopy
from datetime import datetime, timezone
from time import time
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from flask import Flask, current_app, g
from flask.testing import FlaskClient
from itsdangerous import SignatureExpired, TimestampSigner, URLSafeTimedSerializer
from sqlalchemy import event
from werkzeug.test import TestResponse

from app.achievements.models import StreakEvent, UserStatistics
from app.api import native_lessons
from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, Module
from app.modules.migrations import seed_initial_modules
from app.modules.service import ModuleService
from app.utils.db import db


def sign_in(client: FlaskClient, app: Flask, user: User) -> dict[str, str]:
    token = uuid4().hex
    with client.session_transaction() as session:
        session.clear()
        session['_user_id'] = user.get_id()
        session['_fresh'] = True
        session['csrf_token'] = token
    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    return {'X-CSRFToken': URLSafeTimedSerializer(app.secret_key, salt='wtf-csrf-token').dumps(token)}


@pytest.fixture
def receipt(
    app: Flask, client: FlaskClient, db_session: Any, monkeypatch: pytest.MonkeyPatch,
) -> Any:
    clock = {'seconds': 0}

    class ClockSigner(TimestampSigner):
        def get_timestamp(self) -> int:
            return int(time()) + clock['seconds']

    monkeypatch.setattr(native_lessons, '_signer', lambda: URLSafeTimedSerializer(
        current_app.config['SECRET_KEY'], salt='native-course-v1', signer=ClockSigner,
    ))
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    monkeypatch.setitem(app.config, 'SESSION_COOKIE_SECURE', False)
    seed_initial_modules()
    level = CEFRLevel.query.filter_by(code='A1').first()
    if level is None:
        level = CEFRLevel(code='A1', name='Synthetic A1', order=1)
        db_session.add(level)
        db_session.flush()
    module = Module(level_id=level.id, number=1, title='Receipt expiry')
    db_session.add(module)
    db_session.flush()
    lessons = [Lessons(
        module_id=module.id, number=number, order=number,
        title='Synthetic quiz ' + str(number), type='quiz', content={'questions': [
            {'type': 'multiple_choice', 'question': 'Choose a greeting.',
             'options': ['Hello', 'Goodbye'], 'correct': 0},
            {'type': 'fill_blank', 'question': 'Type welcome.', 'correct_answer': 'welcome'},
        ]},
    ) for number in (1, 2)]
    db_session.add_all(lessons)
    name = 'expiry_' + uuid4().hex[:12]
    user = User(
        username=name, email=name + '@example.invalid', active=True,
        onboarding_completed=True, onboarding_level='A1', timezone='UTC',
        plan_difficulty='light', last_login=datetime.now(timezone.utc),
    )
    user.set_password(uuid4().hex)
    db_session.add(user)
    db_session.commit()
    ModuleService.grant_default_modules_to_user(user.id)
    headers = sign_in(client, app, user)
    endpoint = f'/curriculum/api/lesson/{lessons[0].id}/practice'
    response = client.get(endpoint)
    assert response.status_code == 200, response.json
    yield {
        'app': app, 'user': user, 'lesson': lessons[0], 'other_lesson': lessons[1],
        'client': client, 'headers': headers, 'endpoint': endpoint,
        'doc': response.json['lesson'], 'clock': clock,
    }
    g.pop('_login_user', None)
    g.pop('csrf_token', None)


def post(
    receipt: dict[str, Any], body: dict[str, Any], endpoint: str | None = None,
) -> TestResponse:
    g.pop('_login_user', None)
    return receipt['client'].post(
        (endpoint or receipt['endpoint']) + '/submit', headers=receipt['headers'], json=body,
    )


def effects(receipt: dict[str, Any]) -> dict[str, Any]:
    uid, lid = receipt['user'].id, receipt['lesson'].id
    progress = LessonProgress.query.filter_by(user_id=uid, lesson_id=lid).first()
    stats = UserStatistics.query.filter_by(user_id=uid).first()
    return deepcopy({
        'progress': None if not progress else {
            'status': progress.status, 'score': progress.score, 'last_score': progress.last_score,
            'best_score': progress.best_score, 'data': progress.data,
            'last_activity': str(progress.last_activity),
        },
        'attempts': [
            (row.attempt_number, row.score, row.passed)
            for row in LessonAttempt.query.filter_by(user_id=uid, lesson_id=lid).order_by(LessonAttempt.id)
        ],
        'xp': stats.total_xp if stats else 0,
        'events': StreakEvent.query.filter_by(user_id=uid).count(),
    })


def read_only_post(
    receipt: dict[str, Any], body: dict[str, Any], endpoint: str | None = None,
) -> TestResponse:
    writes = []

    def capture(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool,
    ) -> None:
        if statement.lstrip().split(maxsplit=1)[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER'}:
            writes.append(statement)

    event.listen(db.engine, 'before_cursor_execute', capture)
    try:
        response = post(receipt, body, endpoint)
    finally:
        event.remove(db.engine, 'before_cursor_execute', capture)
    assert writes == [], writes
    return response


def test_expired_completed_receipt_replays_original_without_extending_grading_ttl(
    receipt: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {'session_token': receipt['doc']['session_token'], 'answers': {'0': '0', '1': 'welcome'}}
    first = post(receipt, body)
    assert first.status_code == 200 and first.json['score'] == 100 and first.json['completed']
    before = effects(receipt)
    receipt['clock']['seconds'] = 21660
    guard = Mock(side_effect=AssertionError('Expired receipt must not assemble/write a new plan'))
    monkeypatch.setattr(native_lessons, '_guard_plan', guard)
    replay = read_only_post(receipt, {**body, 'answers': {'0': '1', '1': 'wrong'}})
    assert replay.status_code == 200 and replay.json == first.json
    assert effects(receipt) == before and guard.call_count == 0
    with pytest.raises(SignatureExpired):
        native_lessons._signer().loads(body['session_token'], max_age=21600)
    assert 'session_token' not in replay.json
    check = receipt['client'].post(
        receipt['endpoint'] + '/check', headers=receipt['headers'],
        json={'session_token': body['session_token'], 'question_id': '0', 'answer': '0'},
    )
    assert check.status_code == 409 and check.json['error'] == 'lesson_changed'
    assert effects(receipt) == before


def test_expired_first_and_correction_receipts_preserve_fifty_percent(receipt: Any) -> None:
    body = {'session_token': receipt['doc']['session_token'], 'answers': {'0': '1', '1': 'welcome'}}
    first = post(receipt, body)
    assert first.json['score'] == 50 and first.json['correction_pending']
    before = effects(receipt)
    receipt['clock']['seconds'] = 21660
    replay = read_only_post(receipt, body)
    assert replay.status_code == 200 and replay.json == first.json
    assert effects(receipt) == before
    correction = receipt['client'].get(receipt['endpoint']).json['lesson']
    assert correction['quiz_phase'] == 'correction'
    corrected = {'session_token': correction['session_token'], 'answers': {'0': '0'}}
    final = post(receipt, corrected)
    assert final.status_code == 200 and final.json['score'] == 50 and final.json['completed']
    before = effects(receipt)
    receipt['clock']['seconds'] += 21660
    replay = read_only_post(receipt, corrected)
    assert replay.status_code == 200 and replay.json == final.json
    assert effects(receipt) == before
    assert len(before['attempts']) == 1 and before['progress']['last_score'] == 50


@pytest.mark.parametrize('missing', ['unsubmitted', 'unknown_nonce'])
def test_expired_without_its_committed_receipt_is_409_and_zero_writes(
    receipt: Any, missing: str,
) -> None:
    token = receipt['doc']['session_token']
    answers = {'0': '0', '1': 'welcome'}
    if missing == 'unknown_nonce':
        assert post(receipt, {'session_token': token, 'answers': answers}).status_code == 200
        claims = native_lessons._signer().loads(token)
        claims['nonce'] = uuid4().hex
        token = native_lessons._signer().dumps(claims)
    before = effects(receipt)
    receipt['clock']['seconds'] = 21660
    response = read_only_post(receipt, {'session_token': token, 'answers': answers})
    assert response.status_code == 409 and response.json['error'] == 'lesson_changed'
    assert effects(receipt) == before


@pytest.mark.parametrize('denial', ['other_user', 'other_lesson', 'bad_signature', 'revoked_access'])
def test_expired_receipt_keeps_identity_signature_and_lesson_access_checks(
    receipt: Any, monkeypatch: pytest.MonkeyPatch, denial: str,
) -> None:
    token = receipt['doc']['session_token']
    body = {'session_token': token, 'answers': {'0': '0', '1': 'welcome'}}
    assert post(receipt, body).json['completed']
    before = effects(receipt)
    receipt['clock']['seconds'] = 21660
    target = None
    if denial == 'other_user':
        name = 'other_' + uuid4().hex[:10]
        user = User(
            username=name, email=name + '@example.invalid', active=True,
            onboarding_completed=True, last_login=datetime.now(timezone.utc),
        )
        user.set_password(uuid4().hex)
        db.session.add(user)
        db.session.commit()
        receipt['headers'] = sign_in(receipt['client'], receipt['app'], user)
    elif denial == 'other_lesson':
        target = f"/curriculum/api/lesson/{receipt['other_lesson'].id}/practice"
    elif denial == 'bad_signature':
        body['session_token'] = token + 'tampered'
    else:
        monkeypatch.setattr('app.curriculum.security.check_lesson_access', Mock(return_value=False))
    response = read_only_post(receipt, body, target)
    assert response.status_code == (409 if denial == 'bad_signature' else 403)
    assert effects(receipt) == before


@pytest.mark.parametrize('nonce', [None, '', '   ', 1, False, [], {}])
def test_expired_legacy_receipt_never_matches_an_invalid_nonce(
    receipt: Any, nonce: Any,
) -> None:
    token = receipt['doc']['session_token']
    body = {'session_token': token, 'answers': {'0': '0', '1': 'welcome'}}
    assert post(receipt, body).json['completed']
    claims = native_lessons._signer().loads(token)
    progress = LessonProgress.query.filter_by(
        user_id=receipt['user'].id, lesson_id=receipt['lesson'].id,
    ).one()
    data = deepcopy(progress.data)
    if nonce is None:
        claims.pop('nonce')
        data['_native_submission'].pop('nonce')
    else:
        claims['nonce'] = nonce
        data['_native_submission']['nonce'] = nonce
    progress.data = data
    db.session.commit()
    body['session_token'] = native_lessons._signer().dumps(claims)
    before = effects(receipt)
    receipt['clock']['seconds'] = 21660
    response = read_only_post(receipt, body)
    assert response.status_code == 409 and response.json['error'] == 'lesson_changed'
    assert effects(receipt) == before
