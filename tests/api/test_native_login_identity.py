"""Username/email login boundaries on a disposable SQLite database only."""
from uuid import uuid4

import pytest
from flask import g
from flask_jwt_extended import decode_token

from app.auth.models import User
from app.utils.db import db
from tests.api.test_account_deletion import native_app as _native_app


@pytest.fixture(scope="module")
def native_app(tmp_path_factory):
    yield from _native_app.__wrapped__(tmp_path_factory)


def login(app, identity, password="exact-test-password"):
    g.pop('_login_user', None)
    return app.test_client().post('/api/login', json={'username': identity, 'password': password})


def user(*, name=None, email=None, password="exact-test-password"):
    name = name or 'login_' + uuid4().hex
    value = User(username=name, email=email or name + '@example.invalid', active=True)
    value.set_password(password)
    db.session.add(value)
    db.session.commit()
    return value


@pytest.mark.parametrize('identity', [
    'x' * 65,
    'x' * 254,
    'x' * 255,
    ' \t\n ',
    'name\x00rest',
    'name\x1brest',
    'name\nrest',
    'name\tlast',
    'name\x7frest',
    'name\u0085rest',
    'person@exam\nple.com',
    'name\ud800rest',
])
def test_malformed_identity_is_a_format_error_instead_of_authentication_failure(native_app, identity):
    response = login(native_app, identity)
    assert response.status_code == 400
    assert response.json['error'] == 'invalid_credentials_format'
    assert 'access_token' not in response.json and 'Set-Cookie' not in response.headers


def test_a_64_character_username_and_outer_whitespace_remain_compatible(native_app):
    name = 'u' + uuid4().hex + 'x' * 31
    assert len(name) == 64
    account = user(name=name)
    for identity in [name, '  ' + name + '  ']:
        response = login(native_app, identity)
        assert response.status_code == 200
        assert response.json['user']['id'] == account.id
        assert decode_token(response.json['access_token'])['sub'] == str(account.id)
    assert login(native_app, name + 'x').status_code == 400


def test_email_longer_than_username_limit_still_logs_in_case_insensitively(native_app):
    email = 'mail.' + uuid4().hex + '@' + ('subdomain-' * 4) + 'example.invalid'
    assert 64 < len(email) <= 120  # Fits the existing users.email column too.
    account = user(email=email)
    response = login(native_app, '  ' + email.upper() + '  ')
    assert response.status_code == 200
    assert response.json['user']['id'] == account.id
    assert response.json['user']['username'] == account.username


def test_email_like_input_keeps_254_character_limit_without_creating_an_account(native_app):
    email = 'a' * 64 + '@' + 'b' * 63 + '.' + 'c' * 63 + '.' + 'd' * 61
    assert len(email) == 254
    before = User.query.count()
    assert login(native_app, email).status_code == 401
    response = login(native_app, email + 'd')
    assert response.status_code == 400 and response.json['error'] == 'invalid_credentials_format'
    assert User.query.count() == before


def test_login_never_trims_or_changes_the_existing_password(native_app):
    password = '  exact-test-password  '
    account = user(password=password)
    assert login(native_app, account.username, password).status_code == 200
    assert login(native_app, account.username, password.strip()).status_code == 401
    assert login(native_app, account.username, ' ').status_code == 401


def test_login_preserves_legacy_unicode_and_spaced_usernames(native_app):
    account = user(name='Семья ' + uuid4().hex[:10])
    assert login(native_app, account.username).status_code == 200


def test_password_unicode_remains_exact_and_invalid_utf8_cannot_raise_server_error(native_app):
    password = 'valid-unicode-🙂-password'
    account = user(password=password)
    assert login(native_app, account.username, password).status_code == 200
    response = login(native_app, account.username, 'broken-\ud800-password')
    assert response.status_code == 400 and response.json['error'] == 'invalid_credentials_format'
