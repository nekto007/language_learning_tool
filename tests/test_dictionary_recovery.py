"""Password recovery preserves the explicit local learning destination only."""
from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from app.auth.routes import get_reset_token, verify_reset_token
from app.study.models import UserWord
from tests.test_dictionary_entry import _form, _user, dictionary_entry as dictionary_entry


def test_forgot_link_and_validation_preserve_word_without_sending(entry: Any) -> None:
    client, target = entry['client'], entry['target']
    _, _, login = _form(client, '/login?'+urlencode({'next': target}))
    forgot = login.select_one('a[href*="reset_password"]')['href']
    assert parse_qs(urlparse(forgot).query) == {'next': [target]}
    action, values, page = _form(client, forgot)
    assert parse_qs(urlparse(page.select_one('.auth-card__footer a')['href']).query) == {'next': [target]}
    response = client.post(action, data={**values, 'email': 'invalid'})
    assert response.status_code == 200
    assert BeautifulSoup(response.data, 'html.parser').select_one('input[name=next]')['value'] == target


@pytest.mark.parametrize('delivery', [True, False])
@pytest.mark.parametrize('with_next', [True, False])
def test_reset_email_keeps_canonical_origin_and_explicit_login(entry: Any, monkeypatch: Any,
                                                             delivery: bool, with_next: bool) -> None:
    client, target = entry['client'], entry['target']
    user = _user(); sender = Mock(return_value=delivery)
    monkeypatch.setitem(entry['app'].config, 'SITE_URL', 'https://llt-english.com')
    monkeypatch.setattr('app.auth.routes.email_sender.send_email', sender)
    start = '/reset_password'+('?' + urlencode({'next': target}) if with_next else '')
    action, fields, _ = _form(client, start)
    sent = client.post(action, data={**fields, 'email': user.email})
    login_path = '/login'+('?' + urlencode({'next': target}) if with_next else '')
    assert sent.status_code == 302
    assert urlparse(sent.location).path == '/login'
    assert parse_qs(urlparse(sent.location).query) == ({'next': [target]} if with_next else {})
    reset_url = sender.call_args.kwargs['context']['reset_url']
    assert urlparse(reset_url).netloc == 'llt-english.com'
    assert parse_qs(urlparse(reset_url).query) == ({'next': [target]} if with_next else {})
    token = urlparse(reset_url).path.rsplit('/', 1)[1]
    assert verify_reset_token(token) == user.id
    action, fields, _ = _form(client, urlparse(reset_url).path + ('?' + urlencode({'next': target}) if with_next else ''))
    failed = client.post(action, data={**fields, 'password': 'New9!ValidPassword', 'password2': 'mismatch'})
    assert failed.status_code == 200 and verify_reset_token(token) == user.id
    form = BeautifulSoup(failed.data, 'html.parser').select_one('form')
    assert parse_qs(urlparse(form['action']).query) == ({'next': [target]} if with_next else {})
    done = client.post(action, data={**fields, 'password': 'New9!ValidPassword', 'password2': 'New9!ValidPassword'})
    assert done.status_code == 302 and urlparse(done.location).path == '/login'
    assert parse_qs(urlparse(done.location).query) == ({'next': [target]} if with_next else {})
    assert verify_reset_token(token) is None
    with client.session_transaction() as session:
        assert '_user_id' not in session  # reset never signs in
    login_action, values, _ = _form(client, login_path)
    logged = client.post(login_action, data={**values, 'username_or_email': user.username, 'password': 'New9!ValidPassword'})
    assert logged.status_code == 302
    if with_next:
        assert urlparse(logged.location).path == target
    assert UserWord.query.filter_by(user_id=user.id, word_id=entry['word'].id).count() == 0


def test_unknown_email_and_invalid_token_keep_destination(entry: Any) -> None:
    client, target = entry['client'], entry['target']
    action, fields, _ = _form(client, '/reset_password?'+urlencode({'next': target}))
    response = client.post(action, data={**fields, 'email': 'absent@example.com'})
    assert urlparse(response.location).path == '/login'
    assert parse_qs(urlparse(response.location).query) == {'next': [target]}
    invalid = client.get('/reset_password/not-a-token?'+urlencode({'next': target}))
    assert urlparse(invalid.location).path == '/reset_password'
    assert parse_qs(urlparse(invalid.location).query) == {'next': [target]}


@pytest.mark.parametrize('endpoint', ['request', 'password'])
def test_csrf_recovery_preserves_local_token_route(entry: Any, endpoint: str) -> None:
    user = _user(); token = get_reset_token(user.id)
    route = '/reset_password'+('/'+token if endpoint == 'password' else '')
    response = entry['client'].post(route+'?'+urlencode({'next': entry['target']}),
                                    data={'csrf_token': 'expired'}, headers={'Referer': 'https://evil.example/stolen'})
    assert response.status_code == 302
    parsed = urlparse(response.location)
    assert not parsed.netloc and parsed.path == route
    assert parse_qs(parsed.query) == {'next': [entry['target']]}
    assert verify_reset_token(token) == user.id


@pytest.mark.parametrize('unsafe', ['https://evil.example/word', '//evil.example/word', '/\\evil.example/word'])
def test_reset_rejects_external_destination_and_csrf_referrer(entry: Any, monkeypatch: Any, unsafe: str) -> None:
    user = _user(); sender = Mock(return_value=True)
    monkeypatch.setitem(entry['app'].config, 'SITE_URL', 'https://llt-english.com')
    monkeypatch.setattr('app.auth.routes.email_sender.send_email', sender)
    route = '/reset_password?'+urlencode({'next': unsafe})
    action, fields, _ = _form(entry['client'], route)
    response = entry['client'].post(action, data={**fields, 'email': user.email})
    assert urlparse(response.location).netloc == ''
    reset_url = sender.call_args.kwargs['context']['reset_url']
    assert urlparse(reset_url).netloc == 'llt-english.com'
    assert 'evil.example' not in parse_qs(urlparse(reset_url).query).get('next', [''])[0]
    expired = entry['client'].post(route, data={'csrf_token': 'expired'}, headers={'Referer': 'https://evil.example'})
    assert not urlparse(expired.location).netloc and 'evil.example' not in expired.location


@pytest.mark.parametrize('email', ['', 'not-an-email', 'x'*255+'@example.com'])
def test_request_errors_are_russian_and_linked_to_email(entry: Any, email: str) -> None:
    action, fields, _ = _form(entry['client'], '/reset_password')
    response = entry['client'].post(action, data={**fields, 'email': email})
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser'); field = page.select_one('#email')
    assert page.select_one('label[for=email]').get_text(strip=True) == 'Электронная почта'
    assert field['autocomplete'] == 'email' and field['maxlength'] == '254'
    assert field['aria-invalid'] == 'true' and field['aria-describedby'] == 'email-errors'
    assert field.has_attr('autofocus') and page.select_one('#email-errors')
    errors = page.select_one('#email-errors').get_text()
    assert any(text in errors for text in ('Введите email.', 'Введите корректный email.', '254 символа'))
    assert not any(text in errors for text in ('This field', 'Invalid email', 'Field cannot'))


@pytest.mark.parametrize('password', ['', 'X9!a', 'aaaaAAAA9'])
def test_password_policy_errors_keep_hints_and_accessible_fields(entry: Any, password: str) -> None:
    token = get_reset_token(_user().id)
    action, fields, page = _form(entry['client'], '/reset_password/'+token)
    assert page.select_one('label[for=password]').get_text(strip=True) == 'Новый пароль'
    assert page.select_one('label[for=password2]').get_text(strip=True) == 'Повторите новый пароль'
    for name in ('password', 'password2'):
        assert page.select_one('#'+name)['autocomplete'] == 'new-password'
    hint = page.select_one('#password-hint').get_text()
    assert all(text in hint for text in ('8 до 128', 'заглавная и строчная', 'спецсимвол', 'abc', 'трёх'))
    failed = entry['client'].post(action, data={**fields, 'password': password, 'password2': password})
    page = BeautifulSoup(failed.data, 'html.parser'); field = page.select_one('#password')
    assert field['aria-invalid'] == 'true' and field.has_attr('autofocus')
    assert field['aria-describedby'].split() == ['password-hint', 'password-errors']
    assert page.select_one('#password-errors')
    assert not any(text in page.select_one('#password-errors').get_text() for text in ('This field', 'Field must'))


def test_confirmation_error_has_own_focus_and_russian_text(entry: Any) -> None:
    token = get_reset_token(_user().id)
    action, fields, _ = _form(entry['client'], '/reset_password/'+token)
    response = entry['client'].post(action, data={**fields, 'password': 'New9!ValidPassword', 'password2': 'different'})
    page = BeautifulSoup(response.data, 'html.parser')
    assert page.select_one('#password2-errors').get_text(strip=True) == 'Пароли не совпадают.'
    assert page.select_one('#password2')['aria-describedby'] == 'password2-errors'
    assert page.select_one('#password2').has_attr('autofocus')
    assert not page.select_one('#password').has_attr('autofocus')


@pytest.mark.parametrize('delivery', [True, False])
def test_existing_and_unknown_email_have_the_same_public_confirmation(entry: Any, monkeypatch: Any,
                                                                    caplog: Any, delivery: bool) -> None:
    user = _user(); sender = Mock(return_value=delivery)
    monkeypatch.setattr('app.auth.routes.email_sender.send_email', sender)
    confirmations = []
    for email in (user.email, 'absent-public@example.com'):
        action, fields, _ = _form(entry['client'], '/reset_password')
        response = entry['client'].post(action, data={**fields, 'email': email}, follow_redirects=True)
        page = BeautifulSoup(response.data, 'html.parser')
        confirmations.append(page.select_one('.public-flashes').get_text(strip=True))
    assert confirmations[0] == confirmations[1]
    assert 'Если этот email зарегистрирован' in confirmations[0]
    assert 'позже' in confirmations[0]
    if not delivery:
        assert 'Password reset email submission failed' in caplog.text
        assert user.email not in caplog.text
        assert sender.call_args.kwargs['context']['reset_url'] not in caplog.text
