"""Real browser FormData and JSON paths, using an isolated SQLite database."""
from copy import deepcopy
from datetime import datetime
from html.parser import HTMLParser
from uuid import uuid4

import pytest

from tests.api.test_account_deletion import native_app as _disposable_app
from tests.api.test_native_full_integration import learner


@pytest.fixture(scope='module')
def web_app(tmp_path_factory):
    for app in _disposable_app.__wrapped__(tmp_path_factory):
        app.config['WTF_CSRF_ENABLED'] = False
        from sqlalchemy import event
        from app.utils.db import db
        def add_timezone(connection, _):
            connection.create_function('timezone', 2, lambda zone, value: value)
        event.listen(db.engine, 'connect', add_timezone)
        db.session.remove()
        db.engine.dispose()
        yield app


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'input':
            self.inputs.append(dict(attrs))


def setup_lesson(app, *, guided=True, kind='grammar'):
    from app.utils.db import db
    from app.curriculum.models import CEFRLevel, Module, Lessons
    from app.grammar_lab.content_catalog import compile_topic, content_digest
    from flask import g
    g.pop('_login_user', None)
    user, _ = learner(app)
    user.is_admin = True
    user.onboarding_completed = True
    level = CEFRLevel.query.filter_by(code='A1').first()
    if not level:
        level = CEFRLevel(code='A1', name='Beginner', order=1)
        db.session.add(level)
        db.session.flush()
    module = Module(level_id=level.id, number=Module.query.count() + 1, title='Web test')
    db.session.add(module)
    db.session.flush()
    rows = [
        dict(type='fill_blank', instruction='Впишите одну форму глагола be.', question='I ___ ready.', correct_answer='am', explanation='I am.'),
        dict(type='multiple_choice', instruction='Выберите одну правильную форму be.', question='She ___ here.', options=['is', 'are'], correct_answer='is', explanation='She is.'),
        dict(type='transformation', instruction='Замените I на we. Запишите предложение.', question='I am ready.', correct_answer='We are ready.', alternatives=['We are prepared.'], explanation='We are.'),
        dict(type='error_correction', instruction='Исправьте форму be. Запишите предложение.', question='She are ready.', correct_answer='She is ready.', explanation='She is.'),
        dict(type='translation', instruction='Переведите предложение на английский язык.', question='Они здесь.', correct_answer='They are here.', explanation='They are.'),
    ]
    authored = dict(version=1, topic_slug='a1-1', title='Web grammar', goal='Формы be.', steps=[
        dict(id='forms', title='Формы', body='I am, she is, we/they are.', exercises=rows[:3]),
        dict(id='practice', title='Практика', body='Сохраняйте смысл предложения.', exercises=rows[3:]),
    ])
    content = compile_topic(authored)
    content['guided_catalog_digest'] = content_digest(authored)
    if not guided:
        content = dict(description='Legacy theory', exercises=[dict(type='fill-blank', question='I ___ ready.', answer='am')])
    if kind == 'final_test':
        content = dict(questions=[dict(type='multiple_choice', question='I ___ ready.', options=['am', 'is'], correct_answer='am')])
    lesson = Lessons(module_id=module.id, number=1, order=1, type=kind, title='Web grammar', content=content)
    db.session.add(lesson)
    db.session.commit()
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['_fresh'] = True
    return user, lesson, client


def answers():
    return {'0': 'am', '1': 'is', '2': 'we are prepared', '3': 'she is ready', '4': 'they are here'}


def url(lesson, route):
    return {'learn': f'/learn/{lesson.id}/?ui=legacy', 'form': f'/curriculum/lesson/{lesson.id}/grammar?ui=legacy',
            'json': f'/curriculum/api/lesson/{lesson.id}/submit'}[route]


def state(user, lesson):
    from app.curriculum.models import LessonProgress, LessonAttempt
    from app.daily_plan.linear.models import QuizErrorLog
    row = LessonProgress.query.filter_by(user_id=user.id, lesson_id=lesson.id).first()
    return (None if row is None else (row.status, row.last_activity, deepcopy(row.data), row.score),
            LessonAttempt.query.filter_by(user_id=user.id, lesson_id=lesson.id).count(),
            QuizErrorLog.query.filter_by(user_id=user.id, lesson_id=lesson.id).count())


@pytest.mark.parametrize('route', ['learn', 'form'])
def test_get_has_all_five_inputs_and_revision(web_app, route):
    _, lesson, client = setup_lesson(web_app)
    response = client.get(url(lesson, route))
    assert response.status_code == 200, (response.location, response.get_data(as_text=True))
    html = response.get_data(as_text=True)
    inputs = Inputs(html).inputs
    assert {i['name'] for i in inputs if i.get('name', '').startswith('answer_')} == {f'answer_{i}' for i in range(5)}
    assert next(i for i in inputs if i.get('name') == 'guided_revision')['value'] == lesson.content['guided_catalog_digest']
    assert 'Замените I на we.' in html and 'Исправьте форму be.' in html


@pytest.mark.parametrize('route', ['learn', 'form', 'json'])
@pytest.mark.parametrize('revision', [None, 'old-revision'])
@pytest.mark.parametrize('existing', [False, True])
def test_stale_revision_has_no_progress_or_attempt_writes(web_app, route, revision, existing):
    from app.utils.db import db
    from app.curriculum.models import LessonProgress
    user, lesson, client = setup_lesson(web_app)
    if existing:
        db.session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id, status='in_progress',
                                    last_activity=datetime(2020, 1, 1), data={'untouched': True}))
        db.session.commit()
    before = state(user, lesson)
    payload = {'answers': answers()} if route == 'json' else {f'answer_{k}': v for k, v in answers().items()}
    if revision is not None:
        payload['guided_revision'] = revision
    response = client.post(url(lesson, route), **({'json': payload} if route == 'json' else {'data': payload}))
    assert response.status_code == 409, response.get_data(as_text=True)
    assert response.json['error'] == 'lesson_changed'
    assert state(user, lesson) == before


@pytest.mark.parametrize('route', ['learn', 'form', 'json'])
def test_current_revision_grades_alternatives_without_final_period(web_app, route):
    user, lesson, client = setup_lesson(web_app)
    payload = {'answers': answers()} if route == 'json' else {f'answer_{k}': v for k, v in answers().items()}
    payload['guided_revision'] = lesson.content['guided_catalog_digest']
    response = client.post(url(lesson, route), headers={'X-Requested-With': 'XMLHttpRequest'},
                           **({'json': payload} if route == 'json' else {'data': payload}))
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json['score'] == 100, response.json
    if route != 'json':
        from app.curriculum.models import LessonProgress
        progress = LessonProgress.query.filter_by(user_id=user.id, lesson_id=lesson.id).one()
        assert progress.data['guided_revision'] == payload['guided_revision']
        assert state(user, lesson)[1] == 1


@pytest.mark.parametrize('route', ['learn', 'form'])
@pytest.mark.parametrize('guided', [True, False])
def test_old_saved_answers_do_not_lock_new_revision(web_app, route, guided):
    from app.utils.db import db
    from app.curriculum.models import LessonProgress
    user, lesson, client = setup_lesson(web_app, guided=guided)
    db.session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id, status='completed', score=100,
        data={'feedback': {'0': {'user_answer': 'STALE-ANSWER'}}, 'guided_revision': 'old-revision'}))
    db.session.commit()
    response = client.get(url(lesson, route))
    assert response.status_code == 200, (response.location, response.get_data(as_text=True))
    field = next(i for i in Inputs(response.get_data(as_text=True)).inputs if i.get('name') == 'answer_0')
    assert field.get('value') == '' and 'readonly' not in field
    row = LessonProgress.query.filter_by(user_id=user.id, lesson_id=lesson.id).one()
    assert row.status == 'completed' and row.data['feedback']['0']['user_answer'] == 'STALE-ANSWER'


@pytest.mark.parametrize('route', ['learn', 'form', 'json'])
def test_legacy_grammar_does_not_require_revision(web_app, route):
    _, lesson, client = setup_lesson(web_app, guided=False)
    payload = {'answers': {'0': 'am'}} if route == 'json' else {'answer_0': 'am'}
    response = client.post(url(lesson, route), headers={'X-Requested-With': 'XMLHttpRequest'},
                           **({'json': payload} if route == 'json' else {'data': payload}))
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json['score'] == 100


def test_numeric_browser_option_is_label_not_index(web_app):
    from app.curriculum.routes.lessons import _grade_web_guided_grammar
    row = dict(type='multiple_choice', question='Choose two.', options=['1', '2', '3'], correct_answer='2', explanation='Two.')
    assert _grade_web_guided_grammar([row], {'0': '2'}, option_text=True)['score'] == 100


@pytest.mark.parametrize('route', ['learn', 'form', 'json'])
@pytest.mark.parametrize('bad', ['missing', 'unknown_option', 'oversized'])
def test_current_revision_invalid_answers_do_not_write(web_app, route, bad):
    user, lesson, client = setup_lesson(web_app)
    values = answers()
    if bad == 'missing':
        del values['3']
    elif bad == 'unknown_option':
        values['1'] = 'not an offered option'
    else:
        values['4'] = 'x' * 2001
    payload = {'answers': values} if route == 'json' else {f'answer_{k}': v for k, v in values.items()}
    payload['guided_revision'] = lesson.content['guided_catalog_digest']
    before = state(user, lesson)
    response = client.post(url(lesson, route), headers={'X-Requested-With': 'XMLHttpRequest'},
                           **({'json': payload} if route == 'json' else {'data': payload}))
    assert response.status_code == 400
    assert response.json['error'] == 'invalid_answers'
    assert state(user, lesson) == before


@pytest.mark.parametrize('route', ['learn', 'form'])
def test_saved_current_feedback_still_renders(web_app, route):
    from app.utils.db import db
    from app.curriculum.models import LessonProgress
    user, lesson, client = setup_lesson(web_app)
    db.session.add(LessonProgress(user_id=user.id, lesson_id=lesson.id, status='completed', score=100,
        data={'feedback': {'0': {'user_answer': 'am', 'status': 'correct'}},
              'guided_revision': lesson.content['guided_catalog_digest']}))
    db.session.commit()
    response = client.get(url(lesson, route))
    assert response.status_code == 200
    field = next(i for i in Inputs(response.get_data(as_text=True)).inputs if i.get('name') == 'answer_0')
    assert field.get('value') == 'am' and 'readonly' in field


def test_final_test_keeps_its_existing_json_grader_without_revision(web_app):
    _, lesson, client = setup_lesson(web_app, kind='final_test')
    response = client.post(url(lesson, 'json'), json={'answers': {'0': 'am'}})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json['score'] == 100


@pytest.mark.parametrize('route', ['learn', 'form', 'json'])
def test_guided_page_cannot_submit_after_restore_to_legacy(web_app, route):
    user, lesson, client = setup_lesson(web_app, guided=False)
    payload = {'answers': {'0': 'am'}} if route == 'json' else {'answer_0': 'am'}
    payload['guided_revision'] = 'revision-before-restore'
    before = state(user, lesson)
    response = client.post(url(lesson, route), **({'json': payload} if route == 'json' else {'data': payload}))
    assert response.status_code == 409
    assert state(user, lesson) == before


@pytest.mark.parametrize('route', ['learn', 'form'])
def test_wrong_answer_keeps_guided_identity_in_error_history(web_app, route):
    from app.daily_plan.linear.models import QuizErrorLog
    user, lesson, client = setup_lesson(web_app)
    values = answers()
    values['0'] = 'are'
    payload = {f'answer_{k}': v for k, v in values.items()}
    payload['guided_revision'] = lesson.content['guided_catalog_digest']
    response = client.post(url(lesson, route), data=payload, headers={'X-Requested-With': 'XMLHttpRequest'})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json['score'] == 80
    assert response.json['feedback']['0']['status'] == 'incorrect'
    error = QuizErrorLog.query.filter_by(user_id=user.id, lesson_id=lesson.id).one()
    assert error.question_payload['guided_revision'] == payload['guided_revision']
    assert error.question_payload['guided_key'] == lesson.content['exercises'][0]['guided_key']


# These assertions cover the versioned legacy renderer and saved legacy drafts.
import pytest as _legacy_pytest
pytestmark = _legacy_pytest.mark.legacy_lesson_ui
