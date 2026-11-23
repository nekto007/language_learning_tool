"""Page ownership rejects old-tab writes without replacing auth or CSRF."""
# ruff: noqa: F811 -- imported pytest fixture is discovered by name.

from flask import Flask, jsonify, request
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFProtect, generate_csrf
import pytest

from app.auth.browser_actor import browser_actor_guard


@pytest.fixture
def browser_app():
    app = Flask(__name__, template_folder='../../app/templates')
    app.config.update(TESTING=True, SECRET_KEY='isolated-browser-actor-test', WTF_CSRF_ENABLED=False,
                      JWT_SECRET_KEY='isolated-browser-actor-test-jwt-32')
    manager = LoginManager(app)
    JWTManager(app)

    class Account(UserMixin):
        def __init__(self, identifier):
            self.id = int(identifier)

    manager.user_loader(Account)
    app.before_request(browser_actor_guard)
    CSRFProtect(app)
    writes = []

    @app.post('/login/<int:identifier>')
    def login(identifier):
        login_user(Account(identifier))
        return jsonify(success=True)

    @app.post('/logout')
    def logout():
        logout_user()
        return jsonify(success=True)

    @app.get('/csrf-token')
    @login_required
    def refresh():
        return jsonify(csrf_token=generate_csrf(), account_id=str(current_user.id))

    @app.route('/write', methods=['POST', 'PUT', 'PATCH', 'DELETE'])
    @login_required
    def write():
        writes.append(current_user.id)
        return jsonify(success=True)

    @app.post('/native')
    @jwt_required()
    def native():
        writes.append(get_jwt_identity())
        return jsonify(success=True)

    @app.post('/webhook')
    def webhook():
        return request.get_data()

    return app, writes


@pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
def test_switching_cookie_account_blocks_old_page_before_any_write(browser_app, method):
    app, writes = browser_app
    client = app.test_client()
    client.post('/login/1')
    client.post('/login/2')
    response = getattr(client, method)('/write', headers={'X-LLT-Account-ID': '1'})
    assert response.status_code == 403 and response.json['account_changed'] is True
    assert response.headers['X-LLT-Account-Changed'] == '1'
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert writes == []


@pytest.mark.parametrize('actor', ['0', '01', '+1', '1 ', '1.0', '', '2147483648'])
def test_noncanonical_markers_are_rejected(browser_app, actor):
    app, writes = browser_app
    client = app.test_client()
    client.post('/login/1')
    assert client.post('/write', headers={'X-LLT-Account-ID': actor}).status_code == 403
    assert writes == []


def test_matching_marker_keeps_csrf_protection_and_accepts_refreshed_token(browser_app):
    app, writes = browser_app
    client = app.test_client()
    client.post('/login/1')
    app.config['WTF_CSRF_ENABLED'] = True
    headers = {'X-LLT-Account-ID': '1'}
    assert client.post('/write', headers=headers).status_code == 400
    token = client.get('/csrf-token', headers=headers).json['csrf_token']
    assert client.post('/write', headers={**headers, 'X-CSRFToken': token}).status_code == 200
    token = client.get('/csrf-token', headers=headers).json['csrf_token']
    assert client.post('/write', headers={**headers, 'X-CSRFToken': token}).status_code == 200
    assert writes == [1, 1]


def test_marker_does_not_change_anonymous_login_logout_or_unmarked_native(browser_app):
    app, writes = browser_app
    client = app.test_client()
    assert client.post('/login/1').status_code == 200
    assert client.post('/logout', headers={'X-LLT-Account-ID': '1'}).status_code == 200
    assert client.get('/csrf-token', headers={'X-LLT-Account-ID': '1'}).status_code == 403
    with app.app_context():
        token = create_access_token(identity='2')
    assert client.post('/native', headers={'Authorization': 'Bearer ' + token}).status_code == 200
    assert writes == ['2']


def test_conflicting_cookie_and_bearer_actors_never_choose_another_account(browser_app):
    app, writes = browser_app
    client = app.test_client()
    client.post('/login/1')
    with app.app_context():
        token = create_access_token(identity='2')
    for actor in ('1', '2'):
        response = client.post('/native', headers={'Authorization': 'Bearer ' + token, 'X-LLT-Account-ID': actor})
        assert response.status_code == 403
    assert writes == []


def test_cross_origin_marker_and_conflicting_form_marker_are_rejected(browser_app):
    app, writes = browser_app
    client = app.test_client()
    client.post('/login/1')
    assert client.post('/write', headers={'X-LLT-Account-ID': '1', 'Origin': 'https://other.example'}).status_code == 403
    assert client.post('/write', data={'_llt_account_id': '2'},
                       headers={'X-LLT-Account-ID': '1'}).status_code == 403
    assert writes == []


def test_unmarked_form_encoded_raw_body_stays_readable(browser_app):
    app, _ = browser_app
    response = app.test_client().post('/webhook', data='payload=original+bytes',
                                      content_type='application/x-www-form-urlencoded')
    assert response.data == b'payload=original+bytes'


def test_marked_multipart_upload_keeps_streamed_files_without_caching_raw_body(browser_app):
    from io import BytesIO

    app, _ = browser_app

    @app.post('/upload')
    def upload():
        return jsonify(file=request.files['book'].read().decode(),
                       raw_body_cached='_cached_data' in request.__dict__)

    client = app.test_client()
    client.post('/login/1')
    response = client.post('/upload', data={'_llt_account_id': '1',
                                           'book': (BytesIO(b'chapter text'), 'book.txt')})
    assert response.status_code == 200
    assert response.json == {'file': 'chapter text', 'raw_body_cached': False}


def test_real_csrf_refresh_is_account_bound_no_store_and_does_not_update_database(native_app):
    from flask import g
    from tests.api.test_native_full_integration import learner
    from app.utils.db import db
    from app.auth.models import User

    user, _ = learner(native_app)
    user.last_login = None
    db.session.commit()
    client = native_app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['_fresh'] = True
    g.pop('_login_user', None)
    response = client.get('/csrf-token', headers={'X-LLT-Account-ID': str(user.id)})
    assert response.status_code == 200 and response.json['account_id'] == str(user.id)
    assert response.json['csrf_token'] and response.headers['Cache-Control'] == 'private, no-store'
    db.session.refresh(user)
    assert user.last_login is None
    assert db.session.get(User, user.id) is not None


from tests.api.test_native_full_integration import native_app as native_app
