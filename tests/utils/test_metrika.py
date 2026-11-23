"""Production-only analytics, private-page isolation and validated grading goals."""
from pathlib import Path

import pytest
from flask import Flask, jsonify, render_template, request
from flask_login import LoginManager, UserMixin

from app.middleware.security import add_security_headers
from app.utils.metrika import GOALS_HEADER, init_metrika, metrika_context


class Account(UserMixin):
    def __init__(self, user_id, admin=False):
        self.id = user_id
        self.is_admin = admin


@pytest.fixture
def metric_app():
    application = Flask(__name__, template_folder=str(
        Path(__file__).resolve().parents[2] / 'app/templates'
    ))
    application.config.update(SECRET_KEY='test', YANDEX_METRIKA_ID='114597985')
    manager = LoginManager(application)
    accounts = {'1': Account('1'), '2': Account('2', admin=True)}
    manager.user_loader(accounts.get)
    init_metrika(application)
    add_security_headers(application)

    def page():
        return render_template('components/_metrika.html', pending_gtag_events=[
            {'name': 'signup_completed', 'params': {'email': 'must-not-leak@example.com'}},
        ])

    for path, endpoint in (
        ('/', 'landing.index'), ('/register', 'auth.register'), ('/login', 'auth.login'),
        ('/dashboard', 'words.dashboard'), ('/admin', 'admin.dashboard'),
        ('/reset-password/secret-token', 'auth.reset_password'),
        ('/account/delete', 'auth.account_deletion'), ('/api/mobile/me', 'api.me'),
    ):
        application.add_url_rule(path, endpoint, page)

    def grade():
        return jsonify(request.get_json()), int(request.args.get('status', 200))

    application.add_url_rule('/curriculum/submit', 'curriculum_lessons.submit_lesson', grade, methods=['POST'])
    application.add_url_rule('/grammar/submit', 'grammar_lab.api_submit_answer', grade, methods=['POST'])
    application.add_url_rule('/curriculum/progress', 'curriculum_lessons.update_lesson_progress', grade, methods=['POST'])
    application.add_url_rule('/curriculum/check-item', 'curriculum_lessons.check_sentence_completion_item', grade, methods=['POST'])
    application.add_url_rule('/curriculum/dictation-word', 'curriculum_lessons.check_dictation_word', grade, methods=['POST'])
    application.add_url_rule('/other', 'study.other', grade, methods=['POST'])
    return application


def context(application, path='/', **kwargs):
    with application.test_request_context(path, base_url='https://llt-english.com', **kwargs):
        return metrika_context()['metrika']


def test_public_counter_and_allowlisted_attribution(metric_app):
    data = context(metric_app, '/?utm_source=linkedin&utm_campaign=first_week&q=private&email=secret#token',
                   headers={'Referer': 'https://chatgpt.com/c/private-chat?token=secret'})
    assert data['id'] == 114597985
    assert data['options']['url'] == 'https://llt-english.com/?utm_source=linkedin&utm_campaign=first_week'
    assert data['options']['referrer'] == 'https://chatgpt.com/'
    assert data['options']['webvisor'] is True
    assert data['options']['trackLinks'] is False
    assert 'ecommerce' not in data['options']


@pytest.mark.parametrize('url', [
    'http://localhost', 'https://localhost', 'https://learn.llt-english.com',
    'https://example.com', 'https://llt-english.com.attacker.example', 'http://llt-english.com',
])
def test_other_hosts_and_http_are_never_tracked(metric_app, url):
    with metric_app.test_request_context('/', base_url=url):
        assert metrika_context()['metrika'] is None


@pytest.mark.parametrize('setting,value', [
    ('TESTING', True), ('DEBUG', True), ('YANDEX_METRIKA_ID', ''),
    ('YANDEX_METRIKA_ID', '114597985<script>'), ('YANDEX_METRIKA_ID', '0'),
])
def test_local_and_disabled_configuration(metric_app, setting, value):
    metric_app.config[setting] = value
    assert context(metric_app) is None


@pytest.mark.parametrize('path', ['/admin', '/reset-password/secret-token', '/account/delete', '/api/mobile/me'])
def test_private_routes_do_not_load_counter_or_relax_csp(metric_app, path):
    response = metric_app.test_client().get(path, base_url='https://llt-english.com')
    assert response.status_code == 200
    assert b'metrika.js' not in response.data
    assert 'mc.yandex' not in response.headers['Content-Security-Policy']
    assert response.headers['X-Frame-Options'] == 'DENY'


@pytest.mark.parametrize('path', ['/register', '/login', '/dashboard'])
def test_forms_and_account_pages_never_enable_replay(metric_app, path):
    assert context(metric_app, path)['options']['webvisor'] is False
    response = metric_app.test_client().get(path, base_url='https://llt-english.com')
    policy = response.headers['Content-Security-Policy']
    directives = dict(part.strip().split(' ', 1) for part in policy.split(';') if part.strip())
    assert 'mc.yandex.md' in directives['frame-src'].split()
    assert directives['frame-ancestors'] == "'none'"
    assert 'child-src' not in directives


def test_authenticated_person_never_gets_replay_and_admin_is_excluded(metric_app):
    for user_id, tracked in [('1', True), ('2', False)]:
        browser = metric_app.test_client()
        with browser.session_transaction(base_url='https://llt-english.com') as session:
            session['_user_id'] = user_id
            session['_fresh'] = True
        response = browser.get('/', base_url='https://llt-english.com')
        assert (b'metrika.js' in response.data) is tracked
        if tracked:
            assert b'"webvisor": false' in response.data
        assert response.headers['X-Frame-Options'] == 'DENY'


def test_rendered_counter_keeps_nonce_and_drops_queued_event_params(metric_app):
    response = metric_app.test_client().get('/', base_url='https://llt-english.com')
    assert b'metrika.js' in response.data
    assert b'114597985' in response.data
    assert b'signup_completed' in response.data
    assert b'must-not-leak' not in response.data
    policy = response.headers['Content-Security-Policy']
    assert 'https://mc.yandex.ru' in policy
    assert 'https://mc.yandex.com.tr' in policy
    assert 'wss://mc.webvisor.com' in policy
    assert 'https://metrika.yandex.ru' in policy
    assert "'nonce-" in policy


@pytest.mark.parametrize('path,payload,expected', [
    ('/grammar/submit', {'is_correct': False}, 'learning_answered'),
    ('/grammar/submit', {'is_correct': True}, 'learning_answered'),
    ('/curriculum/submit', {'passed': False, 'score': 20}, 'learning_answered'),
    ('/curriculum/submit', {'passed': True, 'score': 100}, 'learning_answered,lesson_completed'),
    ('/curriculum/submit', {'completed': True}, 'lesson_completed'),
    ('/curriculum/submit', {'completed': False}, None),
    ('/curriculum/submit', {'passed': True, 'success': False}, None),
    ('/curriculum/progress', {'success': True, 'progress': {'status': 'completed'}}, 'lesson_completed'),
    ('/curriculum/progress', {'success': True, 'progress': {'status': 'in_progress', 'score': 0}}, None),
    ('/curriculum/progress', {'success': False, 'progress': {'status': 'completed'}}, None),
    ('/curriculum/check-item', {'success': True, 'correct': False, 'answer': 'private'}, 'learning_answered'),
    ('/curriculum/dictation-word', {'success': True, 'correct': True}, 'learning_answered'),
    ('/grammar/submit', {'error': 'No answer', 'is_correct': False}, None),
    ('/grammar/submit', {'is_correct': 'false'}, None),
    ('/other', {'passed': True}, None),
])
def test_only_server_confirmed_grading_gets_goals(metric_app, path, payload, expected):
    response = metric_app.test_client().post(path, json=payload, base_url='https://llt-english.com')
    assert response.get_json() == payload  # response contract is unchanged
    assert response.headers.get(GOALS_HEADER) == expected


@pytest.mark.parametrize('status', [400, 403, 409, 429, 500])
def test_failed_response_does_not_trigger_goals(metric_app, status):
    response = metric_app.test_client().post(f'/curriculum/submit?status={status}',
                                            json={'passed': True}, base_url='https://llt-english.com')
    assert GOALS_HEADER not in response.headers


def test_malformed_referrer_and_private_campaign_are_ignored(metric_app):
    data = context(metric_app, '/?utm_source=private@example.com', headers={'Referer': 'http://[invalid'})
    assert data['options']['referrer'] == ''
    assert data['options']['url'] == 'https://llt-english.com/'
