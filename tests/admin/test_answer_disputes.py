"""Exercise the private answer-review inbox through the actual editor forms."""
from __future__ import annotations

from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy import event
from sqlalchemy.orm import scoped_session
from werkzeug.test import TestResponse

from app.admin.audit import AdminAuditLog
from app.admin.routes import answer_disputes as routes
from app.auth.models import User
from app.curriculum.answer_disputes import AnswerDispute, AnswerDisputeReport, record_lab_rejected_answer
from app.curriculum.models import Lessons, Module
from app.grammar_lab.answer_review import effective_content
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.utils.db import db

INDEX = '/admin/answer-disputes'


def _page(resp: TestResponse) -> BeautifulSoup:
    assert resp.status_code == 200
    assert resp.headers['Cache-Control'] == 'private, no-store'
    return BeautifulSoup(resp.data, 'html.parser')


def _field(page: BeautifulSoup, name: str) -> str:
    field = page.select_one(f'input[name="{name}"]')
    assert field is not None
    return str(field['value'])


def _login(client: FlaskClient, user: User) -> None:
    g.pop('_login_user', None)
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['_fresh'] = True
        session['user_id'] = user.id


@pytest.fixture
def lab_case(db_session: scoped_session, test_user: User) -> tuple[AnswerDispute, GrammarExercise]:
    topic = GrammarTopic(slug='editor-' + uuid4().hex, title='Shades', title_ru='Цвета одежды', level='A1')
    db_session.add(topic)
    db_session.flush()
    ex = GrammarExercise(topic_id=topic.id, exercise_type='translation',
                         content={'sentence': 'Красивые туфли', 'correct_answer': 'Nice shoes',
                                  'instruction': 'Translate the phrase.'})
    db_session.add(ex)
    db_session.flush()
    record_lab_rejected_answer(db_session, ex, 'Pretty shoes', 'pretty shoes', user_id=test_user.id)
    db_session.commit()
    return AnswerDispute.query.filter_by(grammar_exercise_id=ex.id).one(), ex


def test_search_filter_page_and_constant_queries(
    admin_client: FlaskClient, test_module: Module, db_session: scoped_session,
    lab_case: tuple[AnswerDispute, GrammarExercise], monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, _ = lab_case
    lesson = Lessons(module_id=test_module.id, number=87, title='A special lesson', type='quiz', content={})
    db_session.add(lesson)
    db_session.flush()
    course_cases = []
    for i, status in enumerate(['pending', 'manual', 'revise', 'applied']):
        c = AnswerDispute(lesson_id=lesson.id, question_id=str(i), status=status, grader_version=1,
                          normalized_answer_hash=str(i), question_revision='v',
                          evidence={'row': {}, 'question': {'prompt': 'Question ' + str(i)}, 'answer': str(i)})
        db_session.add(c)
        course_cases.append(c)
    db_session.commit()
    ids = [c.id for c in course_cases]
    assert _page(admin_client.get(INDEX + '?q=одежды')).select_one('.disputes-open')['href'].endswith('/' + str(case.id))
    for params, expected in [
        ('?source=course&q=special&sort=oldest', ids[:2]),
        ('?q=Pretty+shoes', [case.id]),
        ('?q=%23' + str(case.id) + '&source=lab', [case.id]),
        ('?queue=revise&source=course', [ids[2]]), ('?queue=history&source=course', [ids[3]]),
        ('?q=%25', []),
    ]:
        rows = _page(admin_client.get(INDEX + params)).select('.disputes-open')
        assert [int(link['href'].split('/')[-1]) for link in rows] == expected
    monkeypatch.setattr(routes, '_PER_PAGE', 2)
    sql = []

    def record(_connection: object, _cursor: object, statement: str, *_args: object) -> None:
        if statement.lstrip().lower().startswith('select') and 'answer_dispute' in statement.lower():
            sql.append(statement)

    event.listen(db.engine, 'before_cursor_execute', record)
    try:
        page = _page(admin_client.get(INDEX + '?queue=all&source=course&sort=oldest&page=2'))
    finally:
        event.remove(db.engine, 'before_cursor_execute', record)
    assert [int(a['href'].split('/')[-1]) for a in page.select('.disputes-open')] == ids[2:]
    assert len(sql) == 3


def test_real_preview_apply_and_open_next(
    admin_client: FlaskClient, lab_case: tuple[AnswerDispute, GrammarExercise],
    test_user: User, db_session: scoped_session,
) -> None:
    case, ex = lab_case
    path = f'{INDEX}/{case.id}'
    record_lab_rejected_answer(db_session, ex, 'Lovely shoes', 'lovely shoes')
    db_session.commit()
    other = AnswerDispute.query.filter(AnswerDispute.id != case.id, AnswerDispute.grammar_exercise_id == ex.id).one()
    page = _page(admin_client.get(path))
    assert test_user.username in page.get_text()
    assert page.select_one(f'a[href="/admin/users/{test_user.id}"]')
    assert page.select_one(f'a[href="/admin/grammar-lab/exercises/{ex.id}/edit"]')
    assert 'Красивые туфли' in page.get_text() and 'Nice shoes' in page.get_text()
    form = {'version': _field(page, 'version'), 'action': 'add', 'answer': 'Pretty shoes'}
    preview = _page(admin_client.post(path + '/preview', data=form))
    assert 'Pretty shoes' in preview.get_text() and 'Nice shoes' in preview.get_text()
    assert 'alternatives' not in effective_content(ex)
    token = _field(preview, 'preview_token')

    assert admin_client.post(path + '/decide', data=form).status_code == 409
    assert admin_client.post(f'{INDEX}/{other.id}/decide', data={'preview_token': token}).status_code == 409
    # Additional untrusted form fields never replace the reviewed content.
    applied = admin_client.post(path + '/decide', data={'preview_token': token, 'answer': 'Other',
                                                        'action': 'replace', 'next': '1'})
    assert applied.status_code == 303 and urlsplit(applied.location).path == f'{INDEX}/{other.id}'
    assert case.status == 'applied'
    assert effective_content(ex)['alternatives'] == ['Pretty shoes']
    assert admin_client.post(path + '/decide', data={'preview_token': token}).status_code == 409
    assert AdminAuditLog.query.filter_by(action='answer_dispute.add', target_type='answer_dispute',
                                         target_id=case.id).count() == 1
    assert not _page(admin_client.get(path)).select_one('input[name=version]')


def test_guest_and_learner_cannot_read_or_decide(
    client: FlaskClient, test_user: User, lab_case: tuple[AnswerDispute, GrammarExercise],
) -> None:
    path = f'{INDEX}/{lab_case[0].id}'
    for signed_in in (False, True):
        if signed_in:
            _login(client, test_user)
        for response in (client.get(INDEX), client.get(path), client.post(path + '/preview'), client.post(path + '/decide')):
            assert response.status_code in (302, 403)
            assert 'Pretty shoes' not in response.text


def test_history_shows_editors_variant_and_preserves_reported_answer(
    admin_client: FlaskClient, admin_user: User, lab_case: tuple[AnswerDispute, GrammarExercise],
) -> None:
    case, ex = lab_case
    path = f'{INDEX}/{case.id}'
    page = _page(admin_client.get(path))
    form = {'version': _field(page, 'version'), 'action': 'add', 'answer': 'Attractive shoes'}
    token = _field(_page(admin_client.post(path + '/preview', data=form)), 'preview_token')
    assert admin_client.post(path + '/decide', data={'preview_token': token}).status_code == 303
    assert effective_content(ex)['alternatives'] == ['Attractive shoes']
    page = _page(admin_client.get(path))
    history = page.select_one('section[aria-labelledby="history-heading"]').get_text(' ', strip=True)
    assert 'Attractive shoes' in history and 'Pretty shoes' not in history
    assert admin_user.username in history
    assert 'Pretty shoes' in page.select_one('section[aria-labelledby="exercise-heading"]').get_text()


def test_moderator_can_decide_without_reporter_data(
    client: FlaskClient, db_session: scoped_session, test_user: User, lab_case: tuple[AnswerDispute, GrammarExercise],
) -> None:
    case, ex = lab_case
    moderator = User(username='mod_' + uuid4().hex[:8], email=uuid4().hex + '@example.invalid',
                     is_moderator=True, active=True, onboarding_completed=True)
    moderator.set_password('Synthetic-moderator-test-password')
    db_session.add(moderator)
    db_session.commit()
    _login(client, moderator)
    path = f'{INDEX}/{case.id}'
    page = _page(client.get(path))
    for output in (page, _page(client.get(INDEX))):
        assert test_user.username not in output.get_text()
        assert not output.select_one(f'a[href="/admin/users/{test_user.id}"]')
        assert not output.select_one(f'a[href="/admin/grammar-lab/exercises/{ex.id}/edit"]')
    assert not _page(client.get(INDEX, query_string={'q': test_user.username})).select_one('.disputes-open')
    form = {'action': 'revise', 'version': _field(page, 'version'), 'answer': ''}
    token = _field(_page(client.post(path + '/preview', data=form)), 'preview_token')
    assert client.post(path + '/decide', data={'preview_token': token}).status_code == 303
    assert case.status == 'revise'
    page = _page(client.get(path))
    assert not page.select_one('a[href^="/admin/users/"]')
    moderator.is_moderator = False
    db_session.commit()
    assert client.post(path + '/decide', data={'preview_token': token}).status_code in (302, 403)


def test_replacement_preview_shows_only_answers_the_grader_will_reject(
    admin_client: FlaskClient, db_session: scoped_session, test_user: User,
    lab_case: tuple[AnswerDispute, GrammarExercise],
) -> None:
    _, exercise = lab_case
    exercise.content = {
        **exercise.content,
        'alternatives': ['NICE SHOES!', 'Lovely shoes'],
        'alternative_answers': ['Fine footwear'],
        'acceptable_answers': ['LOVELY SHOES.', 'Elegant footwear'],
    }
    record_lab_rejected_answer(db_session, exercise, 'Heavy boots', 'heavy boots', user_id=test_user.id)
    case = AnswerDispute.query.filter_by(grammar_exercise_id=exercise.id).order_by(AnswerDispute.id.desc()).first()
    path = f'{INDEX}/{case.id}'
    page = _page(admin_client.get(path))
    card = page.select_one('section[aria-labelledby="exercise-heading"]').get_text(' ', strip=True)
    assert all(answer in card for answer in ('NICE SHOES!', 'Fine footwear', 'Elegant footwear'))
    preview = _page(admin_client.post(path + '/preview', data={
        'action': 'replace', 'answer': 'Lovely shoes', 'version': _field(page, 'version'),
    }))
    removed = preview.select_one('#preview-removed-answers').get_text(' ', strip=True)
    assert 'Nice shoes' in removed and 'NICE SHOES!' in removed
    assert all(answer not in removed for answer in ('Lovely shoes', 'LOVELY SHOES.', 'Fine footwear', 'Elegant footwear'))
    token = _field(preview, 'preview_token')
    assert admin_client.post(path + '/decide', data={'preview_token': token}).status_code == 303
    updated = effective_content(exercise)
    assert updated['correct_answer'] == 'Lovely shoes'
    assert updated['alternatives'] == []
    assert updated['alternative_answers'] == ['Fine footwear']
    assert updated['acceptable_answers'] == ['Elegant footwear']


def test_confirmation_requires_same_actor_fresh_source_and_csrf(
    app: Flask, admin_client: FlaskClient, admin_user: User, test_user: User,
    db_session: scoped_session, lab_case: tuple[AnswerDispute, GrammarExercise], monkeypatch: pytest.MonkeyPatch,
) -> None:
    case, ex = lab_case
    path = f'{INDEX}/{case.id}'
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    page = _page(admin_client.get(path))
    csrf = _field(page, 'csrf_token')
    form = {'action': 'add', 'version': _field(page, 'version'), 'answer': 'Pretty shoes'}
    headers = {'Accept': 'application/json'}
    assert admin_client.post(path + '/preview', data=form, headers=headers).status_code == 400
    preview = _page(admin_client.post(path + '/preview', data=form | {'csrf_token': csrf}))
    token = _field(preview, 'preview_token')
    assert admin_client.post(path + '/decide', data={'preview_token': token}, headers=headers).status_code == 400
    test_user.is_moderator = True
    db_session.commit()
    _login(admin_client, test_user)
    data = {'preview_token': token, 'csrf_token': csrf}
    assert admin_client.post(path + '/decide', data=data).status_code == 409
    _login(admin_client, admin_user)
    with monkeypatch.context() as patch:
        patch.setattr(routes, '_PREVIEW_TTL', -1)
        assert admin_client.post(path + '/decide', data=data).status_code == 409
    ex.content = {**ex.content, 'correct_answer': 'Changed key'}
    db_session.commit()
    assert admin_client.post(path + '/decide', data=data).status_code == 409
    assert case.status == 'pending'
    assert 'alternatives' not in effective_content(ex)
    assert AnswerDisputeReport.query.filter_by(dispute_id=case.id).one().thanked_at is None
