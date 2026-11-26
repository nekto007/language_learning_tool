"""Native quiz dispute receipts bind the original rejected check and exact attempt."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier
from typing import Any
from unittest.mock import Mock
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from bs4 import BeautifulSoup
from flask import Flask
from flask_jwt_extended import create_access_token
from flask.testing import FlaskClient
from sqlalchemy import inspect, text
from werkzeug.test import TestResponse

from app.achievements.models import StreakEvent, UserStatistics
from app.api import native_quiz_disputes
from app.auth.models import User
from app.curriculum import answer_review as worker
from app.curriculum.answer_disputes import AnswerDispute, AnswerDisputeReport, NativeCourseDisputeReceipt
from app.curriculum.models import CEFRLevel, LessonAttempt, Lessons, Module
from app.modules.service import ModuleService
from app.notifications.models import Notification
from app.telegram import bot
from app.utils.db import db
from tests.answer_review_fixtures import telegram_admin
from tests.api.test_course_receipt_expiry import receipt, sign_in


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(identity=str(user.id), additional_claims={'auth_version': user.auth_version()})
    return {'Authorization': 'Bearer ' + token}


def _user(role: str = 'learner') -> User:
    name = f'native_quiz_{role}_{uuid4().hex[:10]}'
    user = User(username=name, email=f'{name}@example.invalid', active=True, onboarding_completed=True,
                onboarding_level='A1', timezone='UTC', plan_difficulty='light',
                is_moderator=role == 'moderator', is_admin=role == 'admin')
    user.set_password('synthetic test password')
    db.session.add(user)
    db.session.commit()
    return user


def _doc(client: FlaskClient, path: str, headers: dict[str, str], *, first: bool = True) -> dict:
    opened = client.get(path, headers=headers, query_string={'quiz_flow': 'deferred_v1'} if first else {})
    assert opened.status_code == 200, opened.json
    return opened.json['lesson']


def _check(client: FlaskClient, path: str, headers: dict[str, str], token: str, qid: str, answer: str) -> dict:
    result = client.post(path + '/check', headers=headers, json={
        'session_token': token, 'question_id': qid, 'answer': answer,
    })
    assert result.status_code == 200, result.json
    assert result.headers['Cache-Control'] == 'private, no-store'
    return result.json


def _payload(checked: dict, qid: str, answer: str) -> dict[str, str]:
    assert checked['feedback']['correct'] is False
    return {'dispute_token': checked['dispute_token'], 'question_id': qid, 'answer': answer}


def _page(response: TestResponse) -> BeautifulSoup:
    assert response.status_code == 200
    return BeautifulSoup(response.data, 'html.parser')


def _field(page: BeautifulSoup, name: str) -> str:
    field = page.select_one(f'input[name="{name}"]')
    assert field is not None
    return str(field['value'])


def _approve(app: Flask, dispute_id: int, candidate: str) -> None:
    moderator = _user('moderator')
    client = app.test_client()
    sign_in(client, app, moderator)
    path = f'/admin/answer-disputes/{dispute_id}'
    page = _page(client.get(path))
    preview = _page(client.post(path + '/preview', data={
        'csrf_token': _field(page, 'csrf_token'), 'version': _field(page, 'version'),
        'action': 'add', 'answer': candidate,
    }))
    assert preview.select_one('.disputes-verdict')
    decided = client.post(path + '/decide', data={
        'csrf_token': _field(preview, 'csrf_token'), 'preview_token': _field(preview, 'preview_token'),
    })
    assert decided.status_code == 303


def _notices(user: User) -> list[Notification]:
    return Notification.query.filter_by(user_id=user.id, type='answer_review').all()


def _xp_state(user: User) -> tuple[int, int]:
    stats = UserStatistics.query.filter_by(user_id=user.id).one_or_none()
    return (stats.total_xp if stats else 0), StreakEvent.query.filter_by(user_id=user.id).count()


def test_native_check_reports_exact_choice_and_text_and_editor_sees_source(receipt: dict[str, Any]) -> None:  # noqa: F811
    app, pupil, lesson = (receipt[k] for k in ('app', 'user', 'lesson'))
    client, headers = app.test_client(), _headers(pupil)
    path = f'/api/native/lessons/{lesson.id}'
    xp_before = _xp_state(pupil)
    token = _doc(client, path, headers)['session_token']
    value = '  Greetings  '
    wrong_choice = _payload(_check(client, path, headers, token, '0', '1'), '0', '1')
    wrong_text = _payload(_check(client, path, headers, token, '1', value), '1', value)
    assert 'dispute_token' not in _check(client, path, headers, token, '1', 'welcome')
    assert 'dispute_token' not in _check(client, path, headers, _doc(client, path, headers, first=False)['session_token'],
                                       '1', value)
    web_check = receipt['client'].post(receipt['endpoint'] + '/check', headers=receipt['headers'], json={
        'session_token': receipt['doc']['session_token'], 'question_id': '1', 'answer': value,
    })
    assert web_check.status_code == 200 and 'dispute_token' not in web_check.json
    assert not LessonAttempt.query.filter_by(lesson_id=lesson.id).count()
    assert not AnswerDispute.query.filter_by(lesson_id=lesson.id).count()

    other_headers = _headers(_user())
    for body, auth, status, code in (
        (wrong_text, other_headers, 403, 'access_denied'),
        ({**wrong_choice, 'question_id': '1'}, headers, 400, 'invalid_input'),
        ({**wrong_choice, 'answer': 1}, headers, 400, 'invalid_input'),
        ({**wrong_text, 'answer': value.strip()}, headers, 400, 'invalid_input'),
        ({**wrong_text, 'dispute_token': 'invalid'}, headers, 409, 'dispute_receipt_invalid'),
    ):
        rejected = client.post(path + '/dispute', headers=auth, json=body)
        assert rejected.status_code == status and rejected.json['error'] == code
    assert client.post(path + '/dispute', json=wrong_text).status_code == 401
    assert receipt['client'].post(path + '/dispute', json=wrong_text).status_code == 401
    assert client.post(f'/api/native/lessons/{receipt["other_lesson"].id}/dispute',
                       headers=headers, json=wrong_text).status_code == 403

    ids = []
    for payload in (wrong_choice, wrong_text):
        accepted = client.post(path + '/dispute', headers=headers, json=payload)
        assert accepted.status_code == 200, accepted.json
        assert accepted.headers['Cache-Control'] == 'private, no-store'
        repeat = client.post(path + '/dispute', headers=headers, json=payload)
        assert repeat.status_code == 200 and repeat.json == accepted.json
        ids.append(accepted.json['dispute_id'])
    cases = [db.session.get(AnswerDispute, identifier) for identifier in ids]
    assert [case.evidence['answer'] for case in cases] == ['1', value]
    for case, kind in zip(cases, ('choice', 'text'), strict=True):
        report = AnswerDisputeReport.query.filter_by(dispute_id=case.id).one()
        evidence = NativeCourseDisputeReceipt.query.filter_by(report_id=report.id).one()
        assert report.user_id == pupil.id and report.course_nonce == evidence.nonce
        assert evidence.input_kind == kind and evidence.answer == case.evidence['answer']
    for role in ('moderator', 'admin'):
        person = _user(role)
        browser = app.test_client()
        sign_in(browser, app, person)
        page = _page(browser.get(f'/admin/answer-disputes/{ids[0]}'))
        assert 'Мобильный квиз' in page.text and 'Goodbye' in page.text and lesson.title in page.text
        assert (pupil.username in page.text) is (role == 'admin')
    assert not LessonAttempt.query.filter_by(lesson_id=lesson.id).count()
    assert not _notices(pupil)
    assert _xp_state(pupil) == xp_before


def test_expired_and_changed_checks_are_rejected_but_only_accepted_checks_replay(receipt: dict[str, Any]) -> None:  # noqa: F811
    app, pupil, lesson = (receipt[k] for k in ('app', 'user', 'lesson'))
    client, headers = app.test_client(), _headers(pupil)
    path = f'/api/native/lessons/{lesson.id}'
    token = _doc(client, path, headers)['session_token']
    accepted = _payload(_check(client, path, headers, token, '1', 'greetings'), '1', 'greetings')
    not_sent = _payload(_check(client, path, headers, token, '1', 'GREETINGS'), '1', 'GREETINGS')
    result = client.post(path + '/dispute', headers=headers, json=accepted)
    assert result.status_code == 200
    updated = deepcopy(lesson.content)
    updated['questions'][0]['question'] = 'Pick a greeting.'
    lesson.content = updated
    db.session.commit()
    assert client.post(path + '/dispute', headers=headers, json=accepted).json == result.json
    stale = client.post(path + '/dispute', headers=headers, json=not_sent)
    assert stale.status_code == 409 and stale.json['error'] == 'lesson_changed'
    receipt['clock']['seconds'] = 21601
    expired = client.post(path + '/dispute', headers=headers, json=accepted)
    assert expired.status_code == 409 and expired.json['error'] == 'dispute_session_expired'
    assert NativeCourseDisputeReceipt.query.join(AnswerDisputeReport).filter_by(user_id=pupil.id).count() == 1


@pytest.mark.parametrize('native_first', [False, True])
def test_shared_case_shows_actual_channels_and_keeps_first_evidence(
    receipt: dict[str, Any], native_first: bool,  # noqa: F811
) -> None:
    app, web_user, lesson = (receipt[k] for k in ('app', 'user', 'lesson'))
    native_user = _user()
    ModuleService.grant_default_modules_to_user(native_user.id)
    path = f'/api/native/lessons/{lesson.id}'
    browser, native, headers = receipt['client'], app.test_client(), _headers(native_user)
    native_token = _doc(native, path, headers)['session_token']
    native_answer, web_answer = 'GREETINGS', '  greetings  '
    native_data = _payload(_check(native, path, headers, native_token, '1', native_answer), '1', native_answer)

    def post_native() -> None:
        response = native.post(path + '/dispute', headers=headers, json=native_data)
        assert response.status_code == 200, response.json

    def post_web() -> None:
        response = browser.post(receipt['endpoint'] + '/dispute', headers=receipt['headers'], json={
            'session_token': receipt['doc']['session_token'], 'question_id': '1', 'answer': web_answer,
        })
        assert response.status_code == 200, response.json

    actions = (post_native, post_web) if native_first else (post_web, post_native)
    actions[0]()
    case = AnswerDispute.query.filter_by(lesson_id=lesson.id).one()
    first_evidence = deepcopy(case.evidence)
    actions[1]()
    db.session.refresh(case)
    assert case.evidence == first_evidence
    assert first_evidence['answer'] == (native_answer if native_first else web_answer)
    assert AnswerDispute.query.filter_by(lesson_id=lesson.id).count() == 1
    reports = {report.user_id: report for report in AnswerDisputeReport.query.filter_by(dispute_id=case.id)}
    assert len(reports) == 2
    assert reports[web_user.id].course_web_reported and reports[web_user.id].course_web_answer == web_answer
    assert not reports[native_user.id].course_web_reported
    assert NativeCourseDisputeReceipt.query.filter_by(report_id=reports[native_user.id].id).one().answer == native_answer

    detail = f'/admin/answer-disputes/{case.id}'
    web_label = 'Веб'  # noqa: RUF001 -- Russian UI label.
    native_label = 'Мобильный квиз'
    moderator, admin = _user('moderator'), _user('admin')
    moderator_client, admin_client = app.test_client(), app.test_client()
    sign_in(moderator_client, app, moderator)
    page = _page(moderator_client.get(detail))
    assert f'{web_label} · {native_label}' in page.select_one('#dispute-report-channels').text
    assert page.select_one('.disputes-reporters') is None

    sign_in(admin_client, app, admin)
    page = _page(admin_client.get(detail))
    per_reporter = {row.a.text.split(' · ID ')[0]: row.select_one('.disputes-reporter-channels').text
                    for row in page.select('.disputes-reporters > li')}
    assert per_reporter == {web_user.username: web_label, native_user.username: native_label}

    web_headers = _headers(web_user)
    token = _doc(native, path, web_headers)['session_token']
    proof = _payload(_check(native, path, web_headers, token, '1', native_answer), '1', native_answer)
    assert native.post(path + '/dispute', headers=web_headers, json=proof).json['dispute_id'] == case.id
    assert AnswerDisputeReport.query.filter_by(dispute_id=case.id).count() == 2
    page = _page(admin_client.get(detail))
    per_reporter = {row.a.text.split(' · ID ')[0]: row.select_one('.disputes-reporter-channels').text
                    for row in page.select('.disputes-reporters > li')}
    assert per_reporter[web_user.username] == f'{web_label} · {native_label}'


@pytest.mark.parametrize(('scenario', 'before_send', 'heading'), [
    ('web', ('web',), 'Курс · Веб'),  # noqa: RUF001 -- Russian channel label.
    ('native', ('native',), 'Курс · Мобильный квиз'),  # noqa: RUF001 -- Russian channel label.
    ('web-then-native', ('web', 'native'), 'Курс · Веб · Мобильный квиз'),  # noqa: RUF001 -- Russian channel label.
    ('native-then-web', ('native', 'web'), 'Курс · Веб · Мобильный квиз'),  # noqa: RUF001 -- Russian channel label.
    ('native-after-send', ('web',), 'Курс · Веб'),  # noqa: RUF001 -- Russian channel label.
    ('legacy', ('web',), 'Курс'),  # noqa: RUF001 -- Russian card title.
])
def test_telegram_dispute_channels_and_private_notification_links(
    receipt: dict[str, Any], monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    scenario: str, before_send: tuple[str, ...], heading: str,
) -> None:
    app, web_user, lesson = (receipt[key] for key in ('app', 'user', 'lesson'))
    native_user = _user()
    ModuleService.grant_default_modules_to_user(native_user.id)
    native, headers = app.test_client(), _headers(native_user)
    path = f'/api/native/lessons/{lesson.id}'
    answer = 'greetings'
    native_token = _doc(native, path, headers)['session_token']
    native_data = _payload(_check(native, path, headers, native_token, '1', answer), '1', answer)
    web_data = {'session_token': receipt['doc']['session_token'], 'question_id': '1', 'answer': answer}
    for key, value in {'OPENAI_API_KEY': 'test-key', 'OPENAI_MODEL': 'test-model',
                       'TELEGRAM_BOT_TOKEN': 'test-token', 'SITE_URL': 'https://site.example.invalid'}.items():
        monkeypatch.setitem(app.config, key, value)
    classify = Mock(return_value={'label': 'valid_variant', 'reason': 'Synthetic verdict', 'model': 'test-model'})
    send = Mock(return_value=True)
    monkeypatch.setattr(worker.ai, 'classify', classify)
    monkeypatch.setattr(bot, 'send_message', send)

    def report(channel: str) -> AnswerDispute:
        if channel == 'web':
            client = receipt['client']
            sign_in_headers = sign_in(client, app, web_user)
            response = client.post(receipt['endpoint'] + '/dispute', headers=sign_in_headers, json=web_data)
        else:
            response = native.post(path + '/dispute', headers=headers, json=native_data)
        assert response.status_code == 200, response.json
        return AnswerDispute.query.filter_by(lesson_id=lesson.id).one()

    with telegram_admin() as binding:
        case = report(before_send[0])
        assert report(before_send[0]).id == case.id
        if scenario == 'legacy':
            older = AnswerDisputeReport.query.filter_by(dispute_id=case.id).one()
            older.course_web_reported = False
            older.course_web_answer = None
            older.course_nonce = None
            db.session.commit()
        assert worker.process_one() and case.status == 'ready'
        if len(before_send) == 2:
            assert report(before_send[1]).id == report(before_send[1]).id == case.id
        assert worker.process_one() and case.status == 'notified'
        send.assert_called_once()
        classify.assert_called_once()
        recipient, message = send.call_args.args
        assert recipient == binding.telegram_id
        level = lesson.module.level.code
        assert message.splitlines()[1] == f'{heading} · {level} · Модуль 1 «{lesson.module.title}»'
        assert f'Урок {lesson.id} «{lesson.title}», вопрос 2' in message
        assert 'Type welcome.' in message and answer in message
        button, = send.call_args.kwargs['reply_markup']['inline_keyboard'][0]
        assert button['url'] == f'https://site.example.invalid/admin/answer-disputes/{case.id}'
        moderator = app.test_client()
        sign_in(moderator, app, _user('moderator'))
        detail_path = urlsplit(button['url']).path
        page = _page(moderator.get(detail_path))
        channels = page.select_one('#dispute-report-channels')
        if scenario == 'legacy':
            assert channels is None
        else:
            assert channels and heading.split(' · ', 1)[1] in channels.get_text(' ', strip=True)
        if scenario == 'native-after-send':
            assert report('native').id == case.id
            assert not worker.process_one()
            send.assert_called_once()
        assert not worker.process_one()

        assert not _notices(web_user) and not _notices(native_user)
        _approve(app, case.id, answer)
        expected = {'web'} if scenario == 'legacy' else set(before_send)
        if scenario == 'native-after-send':
            expected.add('native')
        assert AnswerDisputeReport.query.filter_by(dispute_id=case.id).count() == len(expected)
        assert not LessonAttempt.query.filter_by(lesson_id=lesson.id).count()
        outsider, unauthorized = _user(), app.test_client()
        for channel, owner in (('web', web_user), ('native', native_user)):
            author = app.test_client()
            sign_in(author, app, owner)
            response = author.get('/api/notifications/list')
            notices = [notice for notice in response.json['notifications'] if notice['type'] == 'answer_review']
            if channel not in expected:
                assert notices == []
                continue
            notice, = notices
            assert 'принимает твой вариант' in notice['message'] and lesson.title in notice['message']
            assert notice['link'] == f'/learn/{lesson.id}/'
            assert author.get(notice['link']).status_code == 200
            assert author.get(detail_path).status_code in (302, 403)
            other_headers = sign_in(unauthorized, app, outsider)
            listing = unauthorized.get('/api/notifications/list')
            assert all(item['id'] != notice['id'] for item in listing.json['notifications'])
            assert unauthorized.post(f'/api/notifications/{notice["id"]}/read', headers=other_headers).status_code == 404
        assert AnswerDispute.query.filter_by(lesson_id=lesson.id).count() == 1


def test_receipt_migration_preserves_old_web_and_lab_disputes(app: Flask) -> None:
    from importlib import import_module

    if db.engine.dialect.name != 'postgresql':
        pytest.skip('Uses a private PostgreSQL schema')
    migration = import_module('migrations.versions.20261126_native_quiz_disputes')
    schema = 'quiz_dispute_' + uuid4().hex[:12]
    with db.engine.connect() as connection, connection.begin() as transaction:
        connection.execute(text(f'CREATE SCHEMA {schema}'))
        connection.execute(text(f'SET LOCAL search_path TO {schema}'))
        connection.execute(text('CREATE TABLE answer_disputes (id INTEGER PRIMARY KEY, lesson_id INTEGER, evidence JSON)'))
        connection.execute(text('CREATE TABLE answer_dispute_reports (id INTEGER PRIMARY KEY, dispute_id INTEGER)'))
        connection.execute(text("""
            INSERT INTO answer_disputes VALUES (1, 23, '{"answer":"Historical web value"}'),
            (2, NULL, '{"answer":"Historical Grammar Lab value"}'), (3, 24, '{"answer":"Anonymous"}')
        """))
        connection.execute(text('INSERT INTO answer_dispute_reports VALUES (1, 1), (2, 2)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text("""
                SELECT course_web_reported, course_web_answer FROM answer_dispute_reports ORDER BY id
            """)).all() == [(True, None), (False, None)]
            connection.execute(text('INSERT INTO answer_dispute_reports (id, dispute_id) VALUES (3, 1)'))
            connection.execute(text("""
                INSERT INTO native_course_dispute_receipts VALUES ('fixture', 3, 'nonce', 'text', '  Greetings  ')
            """))
            assert connection.execute(text('SELECT answer FROM native_course_dispute_receipts')).scalar() == '  Greetings  '
            assert inspect(connection).get_indexes('native_course_dispute_receipts', schema=schema)
            connection.execute(text('DELETE FROM answer_dispute_reports WHERE id = 3'))
            assert connection.execute(text('SELECT count(*) FROM native_course_dispute_receipts')).scalar() == 0
            migration.downgrade()
            assert set(inspect(connection).get_table_names(schema=schema)) == {'answer_dispute_reports', 'answer_disputes'}
            assert connection.execute(text('SELECT id, dispute_id FROM answer_dispute_reports ORDER BY id')).all() == [
                (1, 1), (2, 2),
            ]
            assert connection.execute(text("SELECT evidence ->> 'answer' FROM answer_disputes ORDER BY id")).scalars().all() == [
                'Historical web value', 'Historical Grammar Lab value', 'Anonymous',
            ]
        transaction.rollback()


@pytest.mark.parametrize(('submitted', 'expected'), [('greetings', 100), ('GREETINGS', 50), ('welcome', 100)])
def test_after_submit_only_exact_rejected_value_can_receive_credit(
    receipt: dict[str, Any], submitted: str, expected: int,  # noqa: F811
) -> None:
    app, pupil, lesson = (receipt[k] for k in ('app', 'user', 'lesson'))
    client, headers = app.test_client(), _headers(pupil)
    path = f'/api/native/lessons/{lesson.id}'
    token = _doc(client, path, headers)['session_token']
    original = _payload(_check(client, path, headers, token, '1', 'greetings'), '1', 'greetings')
    accepted = client.post(path + '/dispute', headers=headers, json=original)
    assert accepted.status_code == 200
    late = _payload(_check(client, path, headers, token, '0', '1'), '0', '1')
    body = {'session_token': token, 'answers': {'0': '0', '1': submitted}}
    response = client.post(path + '/submit', headers=headers, json=body)
    assert response.status_code == 200 and response.json['score'] == (100 if submitted == 'welcome' else 50)
    attempt = LessonAttempt.query.filter_by(lesson_id=lesson.id).one()
    identity = attempt.id
    closed = client.post(path + '/dispute', headers=headers, json=late)
    assert closed.status_code == 409 and closed.json['error'] == 'dispute_session_closed'
    if submitted != 'welcome':
        document = _doc(client, path, headers)
        assert document['quiz_phase'] == 'correction'
        assert 'dispute_token' not in _check(client, path, headers, document['session_token'], '1', 'greetings')
    xp_before = _xp_state(pupil)
    _approve(app, accepted.json['dispute_id'], 'greetings')
    db.session.refresh(attempt)
    assert attempt.id == identity and attempt.score == expected
    report = AnswerDisputeReport.query.filter_by(dispute_id=accepted.json['dispute_id']).one()
    assert (report.credited_at is not None) is (submitted == 'greetings')
    notice, = _notices(pupil)
    assert ('Ответ зачтён' in notice.message) is (submitted == 'greetings')
    assert _xp_state(pupil) == xp_before
    assert client.post(path + '/dispute', headers=headers, json=original).json == accepted.json
    assert client.post(path + '/submit', headers=headers, json=body).json['score'] == expected
    assert LessonAttempt.query.filter_by(lesson_id=lesson.id).count() == len(_notices(pupil)) == 1


def test_approval_before_submit_leaves_attempt_creation_to_the_normal_route(receipt: dict[str, Any]) -> None:  # noqa: F811
    app, pupil, lesson = (receipt[k] for k in ('app', 'user', 'lesson'))
    client, headers = app.test_client(), _headers(pupil)
    path = f'/api/native/lessons/{lesson.id}'
    token = _doc(client, path, headers)['session_token']
    payload = _payload(_check(client, path, headers, token, '1', 'greetings'), '1', 'greetings')
    result = client.post(path + '/dispute', headers=headers, json=payload)
    assert result.status_code == 200
    xp_before = _xp_state(pupil)
    _approve(app, result.json['dispute_id'], 'greetings')
    assert not LessonAttempt.query.filter_by(lesson_id=lesson.id).count()
    assert _xp_state(pupil) == xp_before
    notice, = _notices(pupil)
    assert 'Ответ зачтён' not in notice.message and 'принимает твой вариант' in notice.message
    checked = _check(client, path, headers, token, '1', 'greetings')
    assert checked['feedback']['correct'] and 'dispute_token' not in checked
    submitted = client.post(path + '/submit', headers=headers, json={
        'session_token': token, 'answers': {'0': '0', '1': 'greetings'},
    })
    assert submitted.status_code == 200 and submitted.json['score'] == 100
    assert LessonAttempt.query.filter_by(lesson_id=lesson.id).count() == len(_notices(pupil)) == 1


def test_parallel_identical_reports_commit_one_receipt(app: Flask, monkeypatch: pytest.MonkeyPatch) -> None:
    if db.engine.dialect.name != 'postgresql':
        pytest.skip('Requires independent PostgreSQL transactions')
    level = CEFRLevel(code='Q9', name='Synthetic native dispute race')
    lesson = Lessons(module=Module(level=level, number=1, title='Synthetic dispute module'),
                     number=1, title='Synthetic native dispute race', type='quiz', content={'questions': [
                         {'type': 'multiple_choice', 'question': 'Pick a tree.',
                          'options': ['Oak', 'Rose'], 'correct_index': 0},
                     ]})
    db.session.add(lesson)
    pupil = _user()
    lesson_id, level_id, user_id = lesson.id, level.id, pupil.id
    client, headers = app.test_client(), _headers(pupil)
    path = f'/api/native/lessons/{lesson_id}'
    monkeypatch.setattr('app.curriculum.security.check_lesson_access', lambda lesson_id: True)
    monkeypatch.setattr('app.api.native_lessons._guard_plan', lambda lesson_id: 'curriculum')
    token = _doc(client, path, headers)['session_token']
    pending = _payload(_check(client, path, headers, token, '0', '1'), '0', '1')
    wait = Barrier(2)
    real_lock = native_quiz_disputes.lock_native_course_dispute

    def synchronized(*args: Any, **kwargs: Any) -> AnswerDispute:
        wait.wait(timeout=8)
        return real_lock(*args, **kwargs)

    def submit() -> tuple[int, dict]:
        response = app.test_client().post(path + '/dispute', headers=headers, json=pending)
        return response.status_code, response.json

    monkeypatch.setattr(native_quiz_disputes, 'lock_native_course_dispute', synchronized)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(submit) for _ in range(2)]
            first, second = [req.result(timeout=12) for req in requests]
        assert first == second and first[0] == 200
        case = AnswerDispute.query.filter_by(lesson_id=lesson_id).one()
        report = AnswerDisputeReport.query.filter_by(dispute_id=case.id, user_id=user_id).one()
        assert NativeCourseDisputeReceipt.query.filter_by(report_id=report.id).count() == 1
        assert not LessonAttempt.query.filter_by(lesson_id=lesson_id).count()
    finally:
        db.session.rollback()
        db.session.delete(db.session.get(CEFRLevel, level_id))
        db.session.delete(db.session.get(User, user_id))
        db.session.commit()
