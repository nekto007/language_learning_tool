"""Install and run the guest clothing rehearsal through its real routes."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session
from werkzeug.test import TestResponse

from app.achievements.models import UserStatistics
from app.admin.audit import AdminAuditLog
from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.landing import rehearsal
from app.landing.rehearsal_intents import offer_intent

PUBLIC = '/rehearsal/clothing/'
ADMIN = '/admin/public-pages/rehearsal'
MODULE = '/learn/a1/module-3/'


def scene(topic: str) -> dict:
    return {
        'title': f'Test {topic}', 'task': f'Task about {topic}', 'opening': f'Opening about {topic}',
        'hint': f'Hint for {topic}', 'clarification': f'Please clarify {topic}', 'offer': f'Offer about {topic}',
        'color_reply': f'Color of {topic}', 'other_color_reply': f'Other color of {topic}',
        'accept_label': 'Take it', 'accept_reply': f'Accepted {topic}',
        'decline_label': 'Leave it', 'decline_reply': f'Declined {topic}', 'try_reply': f'Try {topic}',
        'accepted': ['May I move up in size?', 'The fit is off. Another size, please.'],
    }


def get(client: FlaskClient, url: str) -> TestResponse:
    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    return client.get(url)


def post(client: FlaskClient, url: str, data: dict) -> TestResponse:
    g.pop('_login_user', None)
    g.pop('csrf_token', None)
    return client.post(url, data=data)


def form(response: TestResponse) -> dict:
    assert response.status_code == 200
    page = BeautifulSoup(response.data, 'html.parser')
    return {node['name']: node['value'] for node in page.select('form input[type=hidden][name][value]')}


def publish(client: FlaskClient, document: dict) -> None:
    fields = form(get(client, ADMIN))
    raw = json.dumps(document)
    preview = post(client, ADMIN, {**fields, 'document': raw, 'action': 'preview'})
    assert 'preview_token' in form(preview)
    assert post(client, ADMIN, {**form(preview), 'document': raw, 'action': 'publish'}).status_code == 303


def act(client: FlaskClient, response: TestResponse, action: str, reply: str = '') -> TestResponse:
    return post(client, PUBLIC, {**form(response), 'action': action, 'reply': reply})


def login(client: FlaskClient, user: User) -> TestResponse:
    fields = form(get(client, '/login'))
    response = post(client, '/login', {**fields, 'username_or_email': user.username, 'password': 'testpass123'})
    assert response.status_code == 302
    return response


def test_publication_is_private_csrf_checked_and_revision_bound(
    app: Flask, admin_client: FlaskClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    guest = app.test_client()
    assert get(guest, PUBLIC).status_code == 404
    assert get(guest, ADMIN).status_code in (302, 403)
    assert get(admin_client, '/admin/public-pages').data.count(ADMIN.encode()) == 1
    fields = form(get(admin_client, ADMIN))
    assert post(admin_client, ADMIN, {'action': 'preview', 'document': '{}'}).status_code == 302
    invalid = post(admin_client, ADMIN, {**fields, 'document': '{}', 'action': 'preview'})
    assert invalid.status_code == 422 and b'preview_token' not in invalid.data
    assert get(guest, PUBLIC).status_code == 404

    document = {'jacket': scene('coat'), 'shoes': scene('sneakers')}
    raw = json.dumps(document)
    prepared = post(admin_client, ADMIN, {**fields, 'document': raw, 'action': 'preview'})
    token = form(prepared)
    assert b'Test coat' in prepared.data and b'Test sneakers' in prepared.data
    assert get(guest, PUBLIC).status_code == 404
    altered = json.dumps({**document, 'jacket': scene('different coat')})
    assert post(admin_client, ADMIN, {**token, 'document': altered, 'action': 'publish'}).status_code == 409
    assert post(admin_client, ADMIN, {**token, 'document': raw, 'action': 'publish'}).status_code == 303
    assert post(admin_client, ADMIN, {**token, 'document': raw, 'action': 'publish'}).status_code == 409
    assert AdminAuditLog.query.filter_by(action='rehearsal.clothing.publish').count() == 1
    page = get(guest, PUBLIC)
    assert page.status_code == 200 and b'Opening about coat' in page.data
    assert b'May I move up in size?' not in page.data
    assert page.headers['Cache-Control'] == 'private, no-store'


def test_guest_dialogue_waiting_share_and_separate_help_signals(
    app: Flask, admin_client: FlaskClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    clock = [datetime(2026, 2, 2, 14, tzinfo=UTC)]
    monkeypatch.setattr(rehearsal, '_now', lambda: clock[0])
    publish(admin_client, {'jacket': scene('coat'), 'shoes': scene('sneakers')})
    guest = app.test_client()
    opening = get(guest, PUBLIC)
    assert post(guest, PUBLIC, {'action': 'reply', 'reply': 'Bigger size?'}).status_code == 302
    assert guest.get_cookie(rehearsal._COOKIE, path=PUBLIC) is None
    for reply in ("I don't want a bigger jacket.", 'Do you have a smaller jacket?', 'Do you have a bigger box?'):
        opening = act(guest, opening, 'reply', reply)
        assert b'Please clarify coat' in opening.data and b'Offer about coat' not in opening.data
    assert BeautifulSoup(opening.data, 'html.parser').select_one('.rehearsal-repeat span').get_text() == reply
    hinted = act(guest, opening, 'hint')
    assert b'Hint for coat' in hinted.data
    offer = act(guest, hinted, 'reply', 'Could you show me a larger jacket please?')
    assert b'Offer about coat' in offer.data
    color = act(guest, offer, 'offer_reply', 'Does it come in blue?')
    assert b'Color of coat' in color.data
    other_color = act(guest, color, 'offer_reply', 'Do you have it in red?')
    assert b'Other color of coat' in other_color.data
    repeat = act(guest, other_color, 'offer_reply', 'Could you say that again?')
    assert b'Other color of coat' in repeat.data
    first = act(guest, repeat, 'offer_reply', "I'll take the blue jacket.")
    assert b'Accepted coat' in first.data
    share = BeautifulSoup(first.data, 'html.parser').select_one('#scene-link')['value']
    assert share.endswith(PUBLIC) and '?' not in share
    assert b'Opening about coat' in get(app.test_client(), share).data
    cookie = guest.get_cookie(rehearsal._COOKIE, path=PUBLIC)
    payload = rehearsal._signer().loads(cookie.value)
    assert payload['finished'][0]['hint'] is True
    assert payload['finished'][0]['misunderstood'] is True
    assert payload['finished'][0]['asked_repeat'] is True
    assert 'reply' not in payload and 'bigger box' not in str(payload)
    assert act(guest, repeat, 'offer_reply', 'No, thanks.').status_code == 409
    clock[0] += timedelta(days=3, seconds=-1)
    assert b'Opening about sneakers' not in get(guest, PUBLIC).data
    clock[0] += timedelta(seconds=1)
    second = get(guest, PUBLIC)
    assert b'Opening about sneakers' in second.data
    second = act(guest, second, 'reply', 'Could you say that again?')
    assert b'Opening about sneakers' in second.data and b'Please clarify sneakers' not in second.data
    offer = act(guest, second, 'reply', 'Can I try these shoes in a size larger?')
    repeated = act(guest, offer, 'offer_reply', 'Could you repeat that?')
    assert b'Offer about sneakers' in repeated.data
    done = act(guest, repeated, 'offer_reply', 'No, thanks.')
    assert b'Declined sneakers' in done.data
    rows = BeautifulSoup(done.data, 'html.parser').select('.rehearsal-comparison > div')
    assert 'Подсказка была открыта' in rows[0].get_text()
    assert 'Подсказка не открывалась' in rows[1].get_text()
    assert 'Продавец понял реплику' in rows[1].get_text()
    assert all('Вы попросили повторить' in row.get_text() for row in rows)
    assert all('Ответ продавцу введён письменно' in row.get_text() for row in rows)


@pytest.mark.parametrize(('reply', 'intent'), [
    ('Yes, please.', 'accept'), ('Sure.', 'accept'), ('Can I try it on?', 'try'),
    ('No, thank you.', 'decline'), ('Do you have it in red?', 'other_color'), ('Could you repeat that?', 'repeat'),
])
def test_offer_understands_common_free_text(reply: str, intent: str) -> None:
    assert offer_intent(reply) == intent


def test_course_entry_and_auth_cookie_boundaries_leave_course_progress_untouched(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    level = CEFRLevel.query.filter_by(code='A1').first()
    if level is None:
        level = CEFRLevel(code='A1', name='Test level', order=1)
        db_session.add(level)
        db_session.flush()
    module = Module(level_id=level.id, number=3, title='Synthetic module')
    db_session.add(module)
    db_session.flush()
    db_session.add(Lessons(module_id=module.id, number=1, type='grammar', title='Synthetic lesson', content={}))
    other = User(username='pilot-' + uuid4().hex, email='other@example.invalid', active=True, onboarding_completed=True)
    other.set_password('testpass123')
    db_session.add(other)
    db_session.commit()

    client = app.test_client()
    login(client, test_user)
    assert PUBLIC.encode() not in get(client, MODULE).data
    publish(admin_client, {'jacket': scene('coat'), 'shoes': scene('sneakers')})
    module_page = get(client, MODULE)
    assert module_page.status_code == 200 and PUBLIC.encode() in module_page.data

    xp = db_session.query(UserStatistics.total_xp).filter_by(user_id=test_user.id).scalar()
    progress = LessonProgress.query.filter_by(user_id=test_user.id).count()
    active = act(client, get(client, PUBLIC), 'reply', 'May I move up in size?')
    assert b'Offer about coat' in active.data
    earlier = client.get_cookie(rehearsal._COOKIE, path=PUBLIC).value
    assert get(client, '/logout').status_code == 302
    assert client.get_cookie(rehearsal._COOKIE, path=PUBLIC) is None
    assert b'Opening about coat' in get(client, PUBLIC).data
    login(client, other)
    client.set_cookie(rehearsal._COOKIE, earlier, path=PUBLIC)
    assert b'Opening about coat' in get(client, PUBLIC).data
    assert act(client, active, 'offer_reply', 'No, thanks.').status_code == 409
    assert LessonProgress.query.filter_by(user_id=test_user.id).count() == progress
    assert db_session.query(UserStatistics.total_xp).filter_by(user_id=test_user.id).scalar() == xp


def test_old_and_new_editions_are_shown_separately(
    app: Flask, admin_client: FlaskClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 2, 2, tzinfo=UTC)
    monkeypatch.setattr(rehearsal, '_now', lambda: now)
    doc = {'jacket': scene('coat'), 'shoes': scene('sneakers')}
    publish(admin_client, doc)
    guest = app.test_client()
    offer = act(guest, get(guest, PUBLIC), 'reply', 'I need a bigger size.')
    assert b'Accepted coat' in act(guest, offer, 'accept').data
    publish(admin_client, {**doc, 'shoes': scene('boots')})
    monkeypatch.setattr(rehearsal, '_now', lambda: now + timedelta(days=3))
    offer = act(guest, get(guest, PUBLIC), 'reply', 'Could I go a size up?')
    result = act(guest, offer, 'decline')
    assert b'Declined boots' in result.data
    text = BeautifulSoup(result.data, 'html.parser').get_text()
    assert 'Сцены были пройдены в разных редакциях' in text
    assert 'Подсказки в двух сценах' not in text
    assert text.count('Выбран готовый ответ') == 2
    assert 'Ответ продавцу введён письменно' not in text
