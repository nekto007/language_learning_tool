"""Old browser and API credentials cannot survive password recovery."""
import pytest
from flask import g
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token
from flask_login.utils import encode_cookie

from app.auth.models import User
from app.utils.jwt_auth import create_tokens_for_user


NEW_PASSWORD = 'Brand-New-Pass9'


def _request(client, method, path, **kwargs):
    # The session-scoped test app context retains Flask-Login's cached user.
    # Production requests each have their own g; reproduce that boundary.
    g.pop('_login_user', None)
    return getattr(client, method)(path, **kwargs)


def _saved_cookie(client, name):
    cookie = client.get_cookie(name)
    assert cookie is not None
    return {'key': name, 'value': cookie.value, 'domain': cookie.domain}


def test_auth_identity_is_opaque_and_changes_with_password(test_user, db_session):
    old_identity = test_user.get_id()
    version = test_user.auth_version()
    assert old_identity == f'{test_user.id}:{version}'
    assert test_user.password_hash not in old_identity
    assert test_user.salt not in old_identity
    assert User.from_session_id(old_identity) is test_user
    assert User.from_session_id(str(test_user.id)) is None
    test_user.set_password('testpass123')  # Even reusing a password revokes old credentials.
    db_session.commit()
    assert test_user.get_id() != old_identity
    assert not test_user.has_auth_version(version)
    assert User.from_session_id(old_identity) is None
    assert User.from_session_id(test_user.get_id()) is test_user


@pytest.mark.parametrize('identity', [None, 42, '', '1', '1:bad', '1:' + 'x' * 64,
                                     '9999999999:' + 'a' * 64, '1:' + 'a' * 65])
def test_malformed_and_legacy_session_ids_are_rejected(identity):
    assert User.from_session_id(identity) is None


@pytest.mark.parametrize('password_flow', ['change', 'reset'])
def test_password_change_or_reset_revokes_old_cookies_and_tokens(
        app, db_session, test_user, password_flow):
    browser = app.test_client()
    assert _request(browser, 'post', '/login', data={
        'username_or_email': test_user.username,
        'password': 'testpass123', 'remember_me': 'y',
    }).status_code == 302
    old_session = _saved_cookie(browser, 'session')
    old_remember = _saved_cookie(browser, 'remember_token')
    old_tokens = create_tokens_for_user(test_user)
    old_identity = test_user.get_id()
    assert _request(browser, 'get', '/api/words').status_code == 200

    if password_flow == 'change':
        response = _request(browser, 'post', '/change-password', data={
            'current_password': 'testpass123', 'new_password': NEW_PASSWORD,
            'confirm_password': NEW_PASSWORD,
        })
        assert response.status_code == 302
        # Only this freshly verified session remains, without remembered login.
        with browser.session_transaction() as session:
            assert session['_user_id'] == test_user.get_id()
            assert session['_user_id'] != old_identity
            assert session['_fresh'] is True
        assert browser.get_cookie('remember_token') is None
        assert _request(browser, 'get', '/api/words').status_code == 200
    else:
        from app.auth.routes import get_reset_token, verify_reset_token

        reset_token = get_reset_token(test_user.id)
        reset_browser = app.test_client()
        response = _request(reset_browser, 'post', f'/reset_password/{reset_token}', data={
            'password': NEW_PASSWORD, 'password2': NEW_PASSWORD,
        })
        assert response.status_code == 302
        assert verify_reset_token(reset_token) is None
        assert _request(reset_browser, 'get', '/api/words').status_code == 401
        assert _request(browser, 'get', '/api/words').status_code == 401

    db_session.refresh(test_user)
    assert test_user.check_password(NEW_PASSWORD)
    # Replay copied credentials, including remember-only browser restoration.
    for cookies in ((old_session, old_remember), (old_remember,)):
        replay = app.test_client()
        for cookie in cookies:
            replay.set_cookie(**cookie)
        assert _request(replay, 'get', '/api/words').status_code == 401

    api = app.test_client()
    assert _request(api, 'get', '/api/words', headers={
        'Authorization': f'Bearer {old_tokens["access_token"]}',
    }).status_code == 401
    assert _request(api, 'post', '/api/refresh', headers={
        'Authorization': f'Bearer {old_tokens["refresh_token"]}',
    }).status_code == 401
    response = _request(api, 'post', '/api/login', json={
        'username': test_user.username, 'password': NEW_PASSWORD,
    })
    assert response.status_code == 200
    new_tokens = response.get_json()
    assert _request(api, 'get', '/api/words', headers={
        'Authorization': f'Bearer {new_tokens["access_token"]}',
    }).status_code == 200
    assert _request(api, 'post', '/api/refresh', headers={
        'Authorization': f'Bearer {new_tokens["refresh_token"]}',
    }).status_code == 200


def test_signed_legacy_browser_and_remember_cookies_require_relogin(app, test_user):
    browser = app.test_client()
    with browser.session_transaction() as session:
        session['_user_id'] = str(test_user.id)
        session['_fresh'] = True
    assert _request(browser, 'get', '/api/words').status_code == 401
    remembered = app.test_client()
    remembered.set_cookie('remember_token', encode_cookie(str(test_user.id)))
    assert _request(remembered, 'get', '/api/words').status_code == 401


@pytest.mark.parametrize('version', [None, '0' * 64])
def test_legacy_or_wrong_version_jwt_is_rejected(app, test_user, version):
    claims = {} if version is None else {'auth_version': version}
    access = create_access_token(identity=str(test_user.id), additional_claims=claims)
    refresh = create_refresh_token(identity=str(test_user.id), additional_claims=claims)
    api = app.test_client()
    assert _request(api, 'get', '/api/words', headers={
        'Authorization': f'Bearer {access}',
    }).status_code == 401
    assert _request(api, 'post', '/api/refresh', headers={
        'Authorization': f'Bearer {refresh}',
    }).status_code == 401


def test_refresh_checks_current_account_and_claims(app, db_session, test_user):
    tokens = create_tokens_for_user(test_user)
    test_user.is_admin = True
    db_session.commit()
    api = app.test_client()
    response = _request(api, 'post', '/api/refresh', headers={
        'Authorization': f'Bearer {tokens["refresh_token"]}',
    })
    assert response.status_code == 200
    claims = decode_token(response.get_json()['access_token'])
    assert claims['is_admin'] is True
    assert claims['auth_version'] == test_user.auth_version()
    test_user.active = False
    db_session.commit()
    assert _request(api, 'post', '/api/refresh', headers={
        'Authorization': f'Bearer {tokens["refresh_token"]}',
    }).status_code == 401


@pytest.mark.parametrize('payload', [[], ['username'], 5, 'text', None,
    {'username': ['x'], 'password': 'x'}, {'username': 'x', 'password': ['x']},
    {'username': 'x' * 65, 'password': 'x'}, {'username': 'x', 'password': 'x' * 129},
])
def test_api_login_rejects_malformed_credentials(app, payload):
    import json

    response = _request(app.test_client(), 'post', '/api/login', data=json.dumps(payload),
                        content_type='application/json')
    assert response.status_code == 400
