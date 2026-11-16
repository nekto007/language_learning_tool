"""Native lesson contracts; actual JWT/CSRF and graders, isolated persistence."""
from copy import deepcopy
from datetime import datetime, UTC
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from flask_jwt_extended import JWTManager, create_access_token
from flask_login import LoginManager, UserMixin


class Learner(UserMixin):
    id = 7
    username = 'learner'
    active = True

    @property
    def is_active(self):
        return self.active

    def has_auth_version(self, value):
        return value == 1


@pytest.fixture
def native_context(monkeypatch):
    from app import csrf
    from app.api import decorators, native_lessons as native
    from app.curriculum.services.progress_service import ProgressService
    from app.utils.db import db
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='native-lesson-session-test-only',
                      JWT_SECRET_KEY='native-jwt-signing-key-test-only-32', WTF_CSRF_ENABLED=True,
                      RATELIMIT_ENABLED=False)
    csrf.init_app(app)
    JWTManager(app)
    login = LoginManager(app)
    user = Learner()
    login.user_loader(lambda key: user if key == '7' else None)
    monkeypatch.setattr(decorators, 'db_get_user', lambda uid: user if uid == 7 else None)
    lesson = SimpleNamespace(id=42, title='To be', type='grammar',
        module=SimpleNamespace(level=SimpleNamespace(code='A1')),
        content={'description': '<p>I am / she is</p>', 'exercises': [
            {'type': 'fill_in_blank', 'prompt': 'I ___ here.', 'answer': 'am', 'explanation': 'I + am'},
            {'type': 'multiple_choice', 'question': 'She ___ a teacher.', 'options': ['are', 'is'], 'correct': 1}
        ]})
    state = SimpleNamespace(progress=None)
    guard_function = native._guard_plan
    lookup_function = native._lesson_and_progress
    guard = Mock()
    monkeypatch.setattr(native, '_guard_plan', guard)
    monkeypatch.setattr(native, '_lesson_and_progress', lambda key: (lesson, state.progress))
    import app.curriculum.models as models
    monkeypatch.setattr(models, 'LessonProgress', Mock(side_effect=lambda **values: SimpleNamespace(**values)))
    session = Mock()
    monkeypatch.setattr(db, 'session', session)
    writes = []

    def save(uid, target, grade, passing_score):
        writes.append(deepcopy(grade))
        state.progress = SimpleNamespace(last_activity=datetime.now(UTC),
            status='completed' if grade['score'] >= passing_score else 'in_progress', data=deepcopy(grade))
        return state.progress, None

    def save_theory(uid, lid, status, score, data):
        assert score is None
        writes.append(deepcopy(data))
        state.progress = SimpleNamespace(last_activity=datetime.now(UTC), status=status, data=deepcopy(data))
        return state.progress

    monkeypatch.setattr(ProgressService, 'create_or_update_progress', save_theory)
    monkeypatch.setattr(native, '_award_theory_xp', Mock())
    monkeypatch.setattr(ProgressService, 'update_progress_with_grading', save)
    app.register_blueprint(native.api_native_lessons, url_prefix='/api/native')
    with app.app_context():
        token = create_access_token(identity='7', additional_claims={'auth_version': 1})
    return SimpleNamespace(app=app, client=app.test_client(), headers={'Authorization': f'Bearer {token}'},
                           native=native, user=user, lesson=lesson, state=state, writes=writes, guard=guard, guard_function=guard_function, lookup_function=lookup_function, db=session)


def fetch(c):
    response = c.client.get('/api/native/lessons/42', headers=c.headers)
    assert response.status_code == 200
    return response.get_json()['lesson']


def submit(c, token, answers=None, **extra):
    return c.client.post('/api/native/lessons/42/submit', headers=c.headers,
        json={'session_token': token, 'answers': {'0': 'am', '1': '1'} if answers is None else answers, **extra})


def test_get_omits_answer_keys_and_cleans_html(native_context):
    c = native_context
    lesson = fetch(c)
    assert lesson['questions'][0]['prompt'] == 'I ___ here.'
    assert lesson['questions'][1]['options'] == [{'value': '0', 'label': 'are'}, {'value': '1', 'label': 'is'}]
    assert lesson['theory'][0]['body'] == 'I am / she is'
    assert all(not (set(q) & {'answer', 'correct', 'correct_answer', 'explanation'}) for q in lesson['questions'])
    assert c.writes == []


def test_actual_server_grading_persists_result(native_context):
    c = native_context
    response = submit(c, fetch(c)['session_token'])
    assert response.status_code == 200
    data = response.get_json()
    assert data['passed'] is True and data['score'] == 100
    assert data['correct_count'] == data['total_count'] == 2
    assert data['feedback'][1]['expected'] == 'is'
    assert c.state.progress.status == 'completed'
    assert len(c.writes) == 1
    c.db.query.return_value.filter.return_value.with_for_update.return_value.one.assert_called_once()
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'Set-Cookie' not in response.headers


def test_failed_attempt_is_saved_without_completion(native_context):
    c = native_context
    response = submit(c, fetch(c)['session_token'], {'0': 'are', '1': '0'})
    assert response.get_json()['passed'] is False
    assert response.get_json()['score'] == 0
    assert c.state.progress.status == 'in_progress'


def test_retry_after_lost_response_is_not_a_second_attempt(native_context):
    c = native_context
    token = fetch(c)['session_token']
    first = submit(c, token)
    c.guard.side_effect = c.native.NativeLessonError('lesson_locked', 403)
    second = submit(c, token)
    assert first.get_json() == second.get_json()
    assert second.status_code == 200
    assert len(c.writes) == 1


def test_a_different_progress_revision_rejects_an_old_attempt(native_context):
    c = native_context
    token = fetch(c)['session_token']
    c.state.progress = SimpleNamespace(last_activity=datetime.now(UTC), status='in_progress', data={'web': True})
    assert submit(c, token).status_code == 409
    assert not c.writes


def test_changed_content_rejects_stale_answers(native_context):
    c = native_context
    token = fetch(c)['session_token']
    c.lesson.content['exercises'][0]['answer'] = 'was'
    assert submit(c, token).get_json()['error'] == 'lesson_changed'
    assert not c.writes


@pytest.mark.parametrize('body', [[], {'0': 'am'}, {'0': '', '1': '1'}, {'0': 'am', '1': '99'}, {'0': ['am'], '1': '1'}])
def test_invalid_or_partial_answers_never_reach_grading(native_context, body):
    c = native_context
    assert submit(c, fetch(c)['session_token'], body).status_code == 400
    assert not c.writes


def test_client_score_is_not_accepted(native_context):
    c = native_context
    assert submit(c, fetch(c)['session_token'], score=100).status_code == 400
    assert not c.writes


def test_cookie_only_cannot_submit_despite_csrf_exemption(native_context):
    c = native_context
    with c.client.session_transaction() as session:
        session['_user_id'] = '7'
    response = c.client.post('/api/native/lessons/42/submit', json={'answers': {}})
    assert response.status_code == 401
    assert not c.writes


@pytest.mark.parametrize('header', ['', 'Bearer invalid', 'Basic test'])
def test_non_bearer_or_invalid_jwt_never_reaches_handler(native_context, header):
    c = native_context
    assert c.client.get('/api/native/lessons/42', headers={'Authorization': header}).status_code == 401
    c.guard.assert_not_called()


def test_inactive_and_revoked_accounts_are_rejected(native_context):
    c = native_context
    c.user.active = False
    assert c.client.get('/api/native/lessons/42', headers=c.headers).status_code == 403
    c.user.active = True
    with c.app.app_context():
        stale = create_access_token(identity='7', additional_claims={'auth_version': 0})
    assert c.client.get('/api/native/lessons/42', headers={'Authorization': f'Bearer {stale}'}).status_code == 401
    c.guard.assert_not_called()


def test_tampered_seal_is_rejected(native_context):
    c = native_context
    assert submit(c, fetch(c)['session_token']+'bad').status_code == 409
    assert not c.writes


def test_unsupported_exercise_keeps_the_whole_lesson_on_web(native_context):
    c = native_context
    c.lesson.content['exercises'].append({'type': 'match', 'pairs': []})
    assert c.client.get('/api/native/lessons/42', headers=c.headers).status_code == 422
    assert not c.writes


def test_quiz_uses_existing_quiz_grader(native_context):
    c = native_context
    c.lesson.type = 'quiz'
    c.lesson.content = {'questions': [{'type': 'multiple_choice', 'question': 'A greeting?', 'options': ['Hello', 'Bye'], 'correct_answer': 0}]}
    response = submit(c, fetch(c)['session_token'], {'0': '0'})
    assert response.get_json()['score'] == 100
    assert response.get_json()['total_count'] == 1


def test_failed_storage_does_not_claim_success(native_context, monkeypatch):
    from app.curriculum.services.progress_service import ProgressService
    c = native_context
    def fail(*args, **kwargs):
        raise RuntimeError('storage failed')
    monkeypatch.setattr(ProgressService, 'update_progress_with_grading', fail)
    response = submit(c, fetch(c)['session_token'])
    assert response.status_code == 500
    assert response.get_json()['success'] is False
    assert c.state.progress is None


def test_theory_only_grammar_is_saved_without_a_fabricated_grade(native_context):
    c = native_context
    c.lesson.content = {'sections': [{'subtitle': 'To be', 'description': 'Three forms', 'table': [{'pronoun': 'I', 'form': 'am', 'audio': 'private-file.mp3'}]}], 'exercises': []}
    lesson = fetch(c)
    assert lesson['questions'] == []
    assert 'I · am' in lesson['theory'][0]['body']
    assert 'private-file.mp3' not in str(lesson)
    response = submit(c, lesson['session_token'], {})
    assert response.status_code == 200
    assert response.get_json()['score'] is None
    assert response.get_json()['total_count'] == 0
    assert c.state.progress.status == 'completed'
    assert 'score' not in c.writes[0]
    assert submit(c, lesson['session_token'], {}).get_json() == response.get_json()
    assert len(c.writes) == 1


@pytest.mark.parametrize('completed,paused,allowed', [(False,False,False),(True,False,True),(True,True,False)])
def test_required_course_cannot_skip_the_server_plan(native_context, monkeypatch, completed, paused, allowed):
    from flask import g
    import app.daily_plan.service as plans
    import app.achievements.streak_service as streaks
    import app.telegram.queries as summary
    import app.utils.time_utils as times
    c = native_context
    plan = {'mode':'paused' if paused else 'unified', 'required':[
        {'id':'srs:global','kind':'srs','completed':False},
        {'id':'curriculum:42','kind':'curriculum','completed':False,'data':{'lesson_id':42}}], 'optional':[]}
    monkeypatch.setattr(plans,'get_daily_plan_unified',lambda *a,**k:plan)
    monkeypatch.setattr(streaks,'compute_plan_steps',lambda *a,**k:({'srs:global':completed},0,0,0))
    monkeypatch.setattr(summary,'get_daily_summary',lambda *a,**k:{})
    monkeypatch.setattr(times,'get_user_timezone_name',lambda *a,**k:'UTC')
    with c.app.test_request_context():
        g._login_user = c.user
        if allowed:
            c.guard_function(42)
        else:
            with pytest.raises(c.native.NativeLessonError) as error:
                c.guard_function(42)
            assert error.value.status == 403


def test_curriculum_access_is_still_checked(native_context, monkeypatch):
    import app.curriculum.models as models
    import app.curriculum.security as security
    from flask import g
    c = native_context
    query = Mock(); query.get.return_value = c.lesson
    monkeypatch.setattr(models,'Lessons',SimpleNamespace(query=query))
    monkeypatch.setattr(security,'check_lesson_access',lambda key:False)
    with c.app.test_request_context():
        g._login_user = c.user
        with pytest.raises(c.native.NativeLessonError) as error:
            c.lookup_function(42)
        assert error.value.code == 'lesson_locked'


def test_valid_cookie_never_rescues_an_invalid_bearer(native_context):
    c = native_context
    with c.client.session_transaction() as session:
        session['_user_id'] = '7'
    result = c.client.post('/api/native/lessons/42/submit', headers={'Authorization':'Bearer invalid'}, json={})
    assert result.status_code == 401
    assert not c.writes


def test_opening_time_is_server_signed_and_used_for_attempts(native_context):
    c = native_context
    token = fetch(c)['session_token']
    with c.app.app_context():
        started = c.native._signer().loads(token)['started_at']
    assert submit(c, token).status_code == 200
    added = c.db.add.call_args.args[0]
    assert added.started_at == datetime.fromisoformat(started)
    assert added.user_id == 7 and added.lesson_id == 42


def test_oversized_theory_is_rejected_without_silent_truncation(native_context):
    c = native_context
    c.lesson.content['description'] = 'a' * 20001
    response = c.client.get('/api/native/lessons/42', headers=c.headers)
    assert response.status_code == 422
    assert not c.writes
