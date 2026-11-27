"""Search-entry handoff uses existing auth, onboarding and word-saving with the shared application and database fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock
from uuid import uuid4

from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.study.models import UserWord
from app.utils.db import db
from app.words.models import CollectionWords


@pytest.fixture(name='entry')
def dictionary_entry(app: Flask, client: FlaskClient, db_session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    from app.modules.service import ModuleService
    from app.auth import welcome_email
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    monkeypatch.setattr(ModuleService, 'is_module_enabled_for_user', lambda *a, **k: True)
    monkeypatch.setattr(welcome_email, 'enqueue_welcome_email', Mock())
    monkeypatch.setattr('app.auth.routes.email_sender.send_email', Mock(side_effect=AssertionError('No external sends')))
    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    word = CollectionWords(english_word='entry'+uuid4().hex[:10], russian_word='тестовое слово',
                           level='A1', item_type='word', sentences='An artificial example.')
    db_session.add(word)
    db_session.commit()
    value = {'app': app, 'client': client, 'word': word,
             'target': '/dictionary/'+word.english_word}
    yield value
    db.session.rollback(); g.pop('_login_user', None); g.pop('csrf_token', None)


def _form(client: Any, target: str, selector: str = 'form') -> tuple[str, dict[str, str], Any]:
    response = client.get(target)
    assert response.status_code == 200, (response.status_code, response.location)
    page = BeautifulSoup(response.data, 'html.parser')
    form = page.select_one(selector)
    assert form
    values = {field['name']: field.get('value', '') for field in form.select('input[type=hidden][name]')}
    return form['action'], values, page


def _user(*, onboarded: bool = True) -> User:
    name = 'g4_'+uuid4().hex[:10]
    user = User(username=name, email=name+'@example.com', active=True,
                onboarding_completed=onboarded, timezone='UTC')
    user.set_password('Xk9$mP2vL!qw'); db.session.add(user); db.session.commit()
    return user


def _login(entry: dict[str, Any], user: User) -> Any:
    from urllib.parse import urlencode
    action, values, _ = _form(entry['client'], '/login?'+urlencode({'next': entry['target']}))
    return entry['client'].post(action, data={**values, 'username_or_email': user.username, 'password': 'Xk9$mP2vL!qw'})


def test_guest_actions_name_the_exact_word_destination_without_saving(entry: Any) -> None:
    page = BeautifulSoup(entry['client'].get(entry['target']).data, 'html.parser')
    links = page.select('.pubw-hero__actions a[href*="/register"], .pubw-hero__actions a[href*="/login"]')
    assert len(links) == 2
    assert all(parse_qs(urlparse(a['href']).query)['next'] == [entry['target']] for a in links)
    header = page.select('.public-nav__cta a')
    assert header and all(parse_qs(urlparse(a['href']).query)['next'] == [entry['target']] for a in header)
    assert not page.select('[data-save-word]')
    assert UserWord.query.filter_by(word_id=entry['word'].id).count() == 0


def test_dictionary_referral_is_carried_to_both_auth_actions(entry: Any) -> None:
    page = BeautifulSoup(entry['client'].get(entry['target'], query_string={'ref': 'ref123'}).data, 'html.parser')
    links = page.select('.pubw-hero__actions a[href*="/register"], .pubw-hero__actions a[href*="/login"]')
    assert all(parse_qs(urlparse(a['href']).query) == {'next': [entry['target']], 'ref': ['ref123']} for a in links)


def test_login_error_and_switch_preserve_next_ref_and_legacy_preview(entry: Any) -> None:
    from urllib.parse import urlencode
    query = {'next': entry['target'], 'level': 'A1', 'entry': 'preview', 'ref': 'abc123'}
    action, values, _ = _form(entry['client'], '/login?'+urlencode(query))
    failed = entry['client'].post(action, data={**values, 'username_or_email': 'nobody', 'password': 'wrong'})
    assert failed.status_code == 401
    page = BeautifulSoup(failed.data, 'html.parser')
    assert page.select_one('input[name=next]')['value'] == entry['target']
    destination = page.select_one('.auth-card__footer a')['href']
    assert parse_qs(urlparse(destination).query) == {k: [v] for k, v in query.items()}
    _, _, registered = _form(entry['client'], destination)
    assert parse_qs(urlparse(registered.select_one('.auth-card__footer a')['href']).query) == {k: [v] for k, v in query.items()}


def test_signup_validation_onboarding_and_return_require_explicit_word_save(entry: Any) -> None:
    from urllib.parse import urlencode
    client = entry['client']; target = entry['target']
    referrer = _user(); referrer.referral_code = 'g4'+uuid4().hex[:8]; db.session.commit()
    path = '/register?'+urlencode({'next': target, 'level': 'A2', 'ref': referrer.referral_code})
    action, values, _ = _form(client, path)
    name = 'new_'+uuid4().hex[:10]
    data = {**values, 'username': name, 'email': name+'@example.com', 'password': 'Xk9$mP2vL!qw', 'password2': 'mismatch'}
    failed = client.post(action, data=data)
    assert failed.status_code == 200 and target in BeautifulSoup(failed.data, 'html.parser').select_one('input[name=next]')['value']
    data['password2'] = data['password']
    response = client.post(action, data=data)
    assert response.status_code == 302
    assert parse_qs(urlparse(response.location).query)['next'] == [target]
    user = User.query.filter_by(username=name).one()
    assert user.referred_by_id == referrer.id and user.onboarding_level == 'A2'
    assert not UserWord.query.filter_by(user_id=user.id, word_id=entry['word'].id).first()
    wizard_action, wizard_values, _ = _form(client, response.location, '#quick-start form')
    finished = client.post(wizard_action, data=wizard_values)
    assert finished.location == target
    assert not UserWord.query.filter_by(user_id=user.id, word_id=entry['word'].id).first()
    save, fields, _ = _form(client, target, '[data-save-word]')
    assert fields['_llt_account_id'] == str(user.id)
    saved = client.post(save, data=fields)
    assert saved.status_code == 302 and saved.location == target
    page = client.get(target)
    assert page.headers['Cache-Control'] == 'private, no-store'
    assert BeautifulSoup(page.data, 'html.parser').select('[data-word-saved]')


def test_existing_login_returns_to_word_without_creating_a_learning_record(entry: Any) -> None:
    user = _user(); response = _login(entry, user)
    assert response.location == entry['target']
    assert not UserWord.query.filter_by(user_id=user.id, word_id=entry['word'].id).first()
    assert entry['client'].get('/register', query_string={'next': entry['target']}).location == entry['target']


def test_incomplete_and_completed_onboarding_both_keep_an_explicit_destination(entry: Any) -> None:
    user = _user(onboarded=False); user.onboarding_level = 'A1'; db.session.commit()
    response = _login(entry, user)
    action, fields, _ = _form(entry['client'], response.location, '#quick-start form')
    assert fields['next'] == entry['target']
    first = entry['client'].post(action, data=fields)
    assert first.location == entry['target']
    assert entry['client'].get(response.location).location == entry['target']
    assert entry['client'].post(action, data=fields).location == entry['target']


def test_placement_handoff_still_applies_and_returns_to_the_selected_word(entry: Any) -> None:
    import hashlib
    from app.onboarding import placement_engine as engine
    from app.onboarding.placement_bank import bank_digest, validate_bank
    from app.onboarding.placement_models import PlacementAttempt, PlacementBank
    from tests.placement_fixtures import synthetic_bank
    content = validate_bank(synthetic_bank())
    bank = PlacementBank(id=bank_digest(content), label=content['label'], active=True, content=content)
    db.session.add(bank); db.session.commit()
    client = entry['client']; page = client.get('/placement?start=1')
    csrf = BeautifulSoup(page.data, 'html.parser').select_one('meta[name=csrf-token]')['content']
    with client.session_transaction() as saved:
        actor = hashlib.sha256(saved['placement_guest'].encode()).hexdigest()
    result = engine.start(actor, 'quick', scope='starter')
    while result['status'] == 'active':
        result = engine.answer(actor, result['id'], result['question']['id'], '', True)
    assert client.post('/placement/continue', data={'csrf_token': csrf, 'flow': 'starter'}).status_code == 302
    from urllib.parse import urlencode
    action, values, _ = _form(client, '/register?'+urlencode({'next': entry['target']}))
    name = 'placed_'+uuid4().hex[:10]
    response = client.post(action, data={**values, 'username': name, 'email': name+'@example.com',
                                       'password': 'Xk9$mP2vL!qw', 'password2': 'Xk9$mP2vL!qw'})
    assert response.status_code == 302
    user = User.query.filter_by(username=name).one()
    attempt = db.session.get(PlacementAttempt, result['id'])
    assert attempt.user_id == user.id and attempt.applied_at is not None
    assert user.onboarding_completed and user.onboarding_level == 'A1'
    assert client.get(response.location).location == entry['target']
    assert not UserWord.query.filter_by(user_id=user.id, word_id=entry['word'].id).first()


@pytest.mark.parametrize('state', ['new', 'learning', 'review', 'excluded'])
def test_saved_status_and_duplicate_save_preserve_srs(entry: Any, state: str) -> None:
    user = _user(); _login(entry, user)
    user_word = user.set_word_status(entry['word'].id, 1)
    for direction in user_word.directions:
        direction.state = 'review' if state == 'review' else 'learning' if state == 'learning' else 'new'
        direction.interval = 10; direction.repetitions = 3 if state != 'new' else 0
        direction.next_review = datetime.now()+timedelta(days=10)
    user_word.srs_excluded = state == 'excluded'; user_word.recalculate_status(); db.session.commit()
    before = [(d.id, d.state, d.interval, d.repetitions, d.next_review) for d in user_word.directions]
    response = entry['client'].get(entry['target']); page = BeautifulSoup(response.data, 'html.parser')
    assert page.select_one('[data-word-saved]') and not page.select('[data-save-word]')
    if state == 'excluded': assert 'Убрано из повторений' in response.text
    action = f'/update-word-status/{entry["word"].id}/1?next='+entry['target']
    csrf = page.select_one('meta[name=csrf-token]')['content']
    assert entry['client'].post(action, data={'csrf_token': csrf, 'source': 'public_dictionary', '_llt_account_id': user.id}).status_code == 302
    db.session.refresh(user_word)
    assert [(d.id, d.state, d.interval, d.repetitions, d.next_review) for d in user_word.directions] == before
    assert user_word.srs_excluded == (state == 'excluded')
    assert UserWord.query.filter_by(user_id=user.id, word_id=entry['word'].id).count() == 1


def test_public_saved_word_review_returns_to_its_canonical_card(entry: Any) -> None:
    word = entry['word']
    word.english_word += ' blue jay'
    db.session.commit()
    entry['target'] = '/dictionary/' + word.english_word.replace(' ', '_')
    user = _user()
    assert _login(entry, user).status_code == 302
    client = entry['client']
    action, fields, _ = _form(client, entry['target'], '[data-save-word]')
    saved = client.post(action, data=fields)
    assert saved.location == entry['target']
    card = BeautifulSoup(client.get(saved.location).data, 'html.parser')
    cabinet_url = card.select_one('a.pubw-banner__btn[href^="/words/"]')['href']
    assert parse_qs(urlparse(cabinet_url).query) == {'origin': ['public_dictionary']}

    cabinet = client.get(cabinet_url)
    assert cabinet.status_code == 200
    assert 'const wordStudyUrl = ' in cabinet.text
    assert 'origin=public_dictionary' in cabinet.text.split('const wordStudyUrl = ', 1)[1].splitlines()[0]

    params = {'source': 'word_detail', 'word_id': word.id, 'extra_study': 'true'}
    for origin, target in [('public_dictionary', entry['target']), (None, f'/words/{word.id}')]:
        response = client.get('/study/cards', query_string={
            **params, 'origin': origin, 'next': 'https://example.invalid/',
        })
        assert response.status_code == 200
        result = BeautifulSoup(response.data, 'html.parser')
        actions = result.select('#session-complete a[data-standalone-cta]')
        assert [(link['href'], link.get_text(strip=True)) for link in actions] == [(target, 'К слову')]
    assert UserWord.query.filter_by(user_id=user.id, word_id=word.id).count() == 1


def test_forged_public_review_origin_keeps_nonpublic_word_in_cabinet(entry: Any) -> None:
    word = entry['word']
    word.level = 'C2'
    db.session.commit()
    user = _user()
    assert _login(entry, user).status_code == 302
    user.set_word_status(word.id, 1)
    client = entry['client']
    cabinet_url = f'/words/{word.id}'
    assert client.get(entry['target']).status_code == 404
    response = client.get(cabinet_url, query_string={'origin': 'public_dictionary'})
    assert response.status_code == 200
    assert 'origin=public_dictionary' not in response.text.split('const wordStudyUrl = ', 1)[1].splitlines()[0]
    response = client.get('/study/cards', query_string={
        'source': 'word_detail', 'word_id': word.id, 'origin': 'public_dictionary', 'next': entry['target'],
    })
    assert response.status_code == 200
    result = BeautifulSoup(response.data, 'html.parser')
    assert result.select_one(f'#session-complete a[href="{cabinet_url}"]')
    assert not result.select_one(f'#session-complete a[href="{entry["target"]}"]')


def test_disabled_dictionary_keeps_public_meaning_but_does_not_offer_or_accept_save(entry: Any, monkeypatch: Any) -> None:
    from app.modules.service import ModuleService
    user = _user(); _login(entry, user)
    action, fields, _ = _form(entry['client'], entry['target'], '[data-save-word]')
    monkeypatch.setattr(ModuleService, 'is_module_enabled_for_user', lambda *a, **k: False)
    response = entry['client'].get(entry['target'])
    assert response.status_code == 200 and not BeautifulSoup(response.data, 'html.parser').select('[data-save-word]')
    assert 'недоступ' in response.text
    assert entry['client'].post(action, data=fields).status_code == 302
    assert not UserWord.query.filter_by(user_id=user.id, word_id=entry['word'].id).first()
    user.set_word_status(entry['word'].id, 1)
    saved = entry['client'].get(entry['target'])
    assert BeautifulSoup(saved.data, 'html.parser').select('[data-word-saved]')
    assert 'Сохранённый прогресс не изменён' in saved.text
    assert not BeautifulSoup(saved.data, 'html.parser').select('[data-save-word]')


def test_save_database_error_returns_to_the_word_for_retry(entry: Any, monkeypatch: Any) -> None:
    user = _user(); _login(entry, user)
    action, fields, _ = _form(entry['client'], entry['target'], '[data-save-word]')
    monkeypatch.setattr(User, 'set_word_status', Mock(side_effect=SQLAlchemyError('private-db-error')))
    response = entry['client'].post(action, data=fields)
    assert response.status_code == 302 and response.location == entry['target']
    retried = entry['client'].get(response.location)
    assert 'Не удалось сохранить слово' in retried.text and 'private-db-error' not in retried.text
    assert BeautifulSoup(retried.data, 'html.parser').select('[data-save-word]')


def test_old_account_save_form_cannot_save_into_a_switched_account(entry: Any) -> None:
    first = _user(); _login(entry, first)
    action, values, _ = _form(entry['client'], entry['target'], '[data-save-word]')
    second = _user()
    with entry['client'].session_transaction() as session:
        session['_user_id'] = second.get_id(); session['_fresh'] = True
    g.pop('_login_user', None)
    response = entry['client'].post(action, data=values)
    assert response.status_code == 403
    assert not UserWord.query.filter_by(user_id=second.id, word_id=entry['word'].id).first()


@pytest.mark.parametrize('endpoint', ['/login', '/register'])
def test_expired_auth_csrf_without_referrer_keeps_resume(entry: Any, endpoint: str) -> None:
    response = entry['client'].post(endpoint, query_string={'next': entry['target']}, data={})
    assert response.status_code == 302 and parse_qs(urlparse(response.location).query)['next'] == [entry['target']]


def test_expired_save_csrf_returns_to_the_same_word_without_writing(entry: Any) -> None:
    user = _user(); _login(entry, user)
    response = entry['client'].post(f'/update-word-status/{entry["word"].id}/1', query_string={'next': entry['target']}, data={'source': 'public_dictionary'})
    assert response.status_code == 302 and response.location == entry['target']
    assert not UserWord.query.filter_by(user_id=user.id, word_id=entry['word'].id).first()


@pytest.mark.parametrize('target', ['https://evil.example', '//evil.example', '///evil.example', '/\\evil.example'])
def test_external_redirects_never_survive_auth_forms(entry: Any, target: str) -> None:
    from urllib.parse import urlencode
    _, values, page = _form(entry['client'], '/register?'+urlencode({'next': target}))
    assert values['next'] == '/dashboard'
    assert 'evil.example' not in page.select_one('.auth-card__footer a')['href']
