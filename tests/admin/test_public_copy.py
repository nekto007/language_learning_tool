"""Public copy authoring through real admin and anonymous routes."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import Any

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g
from flask.testing import FlaskClient
from itsdangerous import TimestampSigner
from sqlalchemy import event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import scoped_session
from werkzeug.datastructures import MultiDict

from app import public_copy
from app.admin.audit import AdminAuditLog
from app.admin.site_settings import SiteSettings
from app.auth.models import User
from app.landing.analytics import LandingVisit
from app.landing.routes import render_landing
from app.public_copy_markup import digest, editable_defaults
from app.utils.db import db
from app.words.models import CollectionWords
from tests.admin.test_materials import _page
from tests.api.test_grammar_lab_disputes import browser

PAGES = '/admin/public-pages'


def _form(page: BeautifulSoup) -> MultiDict:
    form = page.select_one('input[name=revision]').find_parent('form')
    return MultiDict((field['name'], field.get_text() if field.name == 'textarea' else field['value'])
                     for field in form.select('input[name],textarea[name]'))


def _rendered_faq(page: BeautifulSoup) -> list[list[str]]:
    visible = [[row.summary.get_text(strip=True), row.div.get_text(strip=True)]
               for row in page.select('.land-faq__item')]
    entities = [json.loads(script.string) for script in page.select('script[type="application/ld+json"]')]
    faq = next(entity for entity in entities if entity.get('@type') == 'FAQPage')
    assert visible == [[item['name'], item['acceptedAnswer']['text']] for item in faq['mainEntity']]
    return visible


def _layout(page: BeautifulSoup, selector: str) -> tuple:
    root = page.select_one(selector)
    return (
        [(link.get('href'), link.get('rel')) for link in root.find_all('a')],
        [(node.name, node['id']) for node in root.select('[id]')],
        [node.name for node in root.select('h1, h2, h3')],
        page.select_one('link[rel=canonical]')['href'],
    )


def _as_guest(client: FlaskClient, url: str) -> BeautifulSoup:
    g.pop('_login_user', None)
    response = client.get(url)
    assert response.status_code == 200
    return _page(response)


def test_home_add_remove_and_publish_uses_the_same_faq_and_preserves_links(
    app: Flask, admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    guest = app.test_client()
    baseline = _as_guest(guest, '/')
    links = _layout(baseline, '.land-page')
    old_faq = _rendered_faq(baseline)
    assert len(old_faq) == 8
    g.pop('_login_user', None)
    assert _page(admin_client.get('/admin/materials')).select_one(f'a[href="{PAGES}"]')
    url = PAGES + '/home'
    form = _form(_page(admin_client.get(url)))
    form['text.1.1'] = 'Synthetic headline'
    form['text.seo.title'] = 'Synthetic page title'
    form['text.seo.description'] = 'Synthetic search description'
    form['text.seo.og_title'] = 'Synthetic "social" title'
    form['text.seo.og_description'] = 'Synthetic social & description'
    form['action'] = 'add'
    with_empty_pair = admin_client.post(url, data=form)
    assert with_empty_pair.status_code == 200
    data = _form(_page(with_empty_pair))
    question, answer = 'Synthetic "Q" & test?', 'Synthetic & literal </script> answer.'
    data.setlist('question', [*data.getlist('question')[:-1], question])
    data.setlist('answer', [*data.getlist('answer')[:-1], answer])
    data['action'] = 'remove.0'
    removed = _form(_page(admin_client.post(url, data=data)))
    removed['action'] = 'preview'
    before_visits = LandingVisit.query.count()
    response = admin_client.post(url, data=removed)
    assert response.status_code == 200 and response.headers['X-Robots-Tag'] == 'noindex'
    assert LandingVisit.query.count() == before_visits
    preview = _page(response)
    frame = BeautifulSoup(preview.select_one('iframe')['srcdoc'], 'html.parser')
    assert _rendered_faq(frame) == [*old_faq[1:], [question, answer]]
    assert 'Synthetic headline' in frame.select_one('h1').get_text()
    assert db_session.get(SiteSettings, 'public_copy.home') is None
    assert _rendered_faq(_as_guest(guest, '/')) == old_faq
    g.pop('_login_user', None)
    publish = _form(preview)
    publish['action'] = 'publish'
    assert admin_client.post(url, data=publish).status_code == 303
    assert admin_client.post(url, data=publish).status_code == 409
    live = _as_guest(guest, '/')
    assert _rendered_faq(live) == [*old_faq[1:], [question, answer]]
    assert 'Synthetic headline' in live.select_one('h1').get_text()
    assert live.title.string == 'Synthetic page title'
    assert live.select_one('meta[name=description]')['content'] == 'Synthetic search description'
    assert live.select_one('meta[property="og:title"]')['content'] == 'Synthetic "social" title'
    assert live.select_one('meta[property="og:description"]')['content'] == 'Synthetic social & description'
    assert live.select_one('meta[property="og:url"]')['content'] == baseline.select_one('meta[property="og:url"]')['content']
    assert _layout(live, '.land-page') == links
    assert AdminAuditLog.query.filter_by(action='public_copy.publish.home').count() == 1


@pytest.mark.parametrize(('page', 'url'), [('support', '/support/mobile'), ('privacy', '/privacy')])
def test_legal_copy_retains_inline_links_and_allows_a_second_publication(
    page: str, url: str, app: Flask, admin_client: FlaskClient,
) -> None:
    guest = app.test_client()
    baseline = _as_guest(guest, url)
    layout = _layout(baseline, '.legal-page')
    editor = f'{PAGES}/{page}'
    for title in ('Synthetic initial title', 'Synthetic second title'):
        g.pop('_login_user', None)
        fields = _form(_page(admin_client.get(editor)))
        fields['text.1.1'] = title
        fields['text.seo.title'] = f'{title} & search'
        fields['text.seo.description'] = f'{title} description'
        fields['action'] = 'preview'
        response = admin_client.post(editor, data=fields)
        assert response.status_code == 200
        publish = _form(_page(response))
        publish['action'] = 'publish'
        assert admin_client.post(editor, data=publish).status_code == 303
        updated = _as_guest(guest, url)
        assert updated.select_one('h1').get_text(strip=True) == title
        assert updated.title.string == f'{title} & search'
        assert updated.select_one('meta[name=description]')['content'] == f'{title} description'
        assert _layout(updated, '.legal-page') == layout
    assert AdminAuditLog.query.filter_by(action=f'public_copy.publish.{page}').count() == 2
    if page == 'privacy':
        moved = guest.get('/privacy/')
        assert moved.status_code == 301 and moved.location == '/privacy'
        assert baseline.select_one('#google-data') is not None


def test_permission_and_expired_or_modified_previews(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = PAGES + '/support'
    learner, _ = browser(app, test_user)
    g.pop('_login_user', None)
    for client in (app.test_client(), learner):
        g.pop('_login_user', None)
        assert client.get(url).status_code in (302, 403)
        assert client.post(url, data={'action': 'publish'}).status_code in (302, 403)
    test_user.is_moderator = True
    db_session.commit()
    g.pop('_login_user', None)
    assert learner.get(url).status_code in (302, 403)
    assert learner.post(url, data={'action': 'publish'}).status_code in (302, 403)
    g.pop('_login_user', None)
    draft = _form(_page(admin_client.get(url)))
    draft['text.1.1'] = 'Synthetic private draft'
    draft['action'] = 'preview'
    now = 1_800_000_000
    monkeypatch.setattr(TimestampSigner, 'get_timestamp', lambda _: now)
    publish = _form(_page(admin_client.post(url, data=draft)))
    publish['action'] = 'publish'
    modified = publish.copy()
    modified['text.1.1'] = 'Modified after preview'
    assert admin_client.post(url, data=modified).status_code == 409
    now += 1801
    expired = admin_client.post(url, data=publish)
    assert expired.status_code == 409
    assert _form(BeautifulSoup(expired.text, 'html.parser'))['text.1.1'] == 'Synthetic private draft'
    assert db_session.get(SiteSettings, 'public_copy.support') is None


@pytest.mark.parametrize(('page', 'url'), [('support', '/support/mobile'), ('privacy', '/privacy')])
def test_static_page_falls_back_without_writing_settings(
    page: str, url: str, app: Flask, db_session: scoped_session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest = app.test_client()
    original = _as_guest(guest, url)

    def no_connection(*args: object, **kwargs: object) -> str:
        raise OperationalError('SELECT', None, Exception('Synthetic read failure'))

    monkeypatch.setattr(public_copy, '_read_override', no_connection)
    page_html = _as_guest(guest, url)
    assert page_html.h1.get_text(strip=True) == original.h1.get_text(strip=True)
    assert page_html.title.string == original.title.string
    assert db_session.get(SiteSettings, f'public_copy.{page}') is None


def test_override_changes_only_the_addressed_range_in_the_current_landing_render(
    app: Flask, db_session: scoped_session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(CollectionWords(english_word='synthetic article example', russian_word='Synthetic translation',
                                  sentences='Synthetic sentence.', listening='synthetic.mp3',
                                  get_download=1, frequency_rank=10))
    db_session.commit()
    with app.test_request_context('/'):
        raw = render_landing(editorial_preview=True)
    assert 'Synthetic sentence.' in raw and 'synthetic.mp3' in raw
    original, _ = editable_defaults('home', raw)
    replacement = 'Synthetic title & option'
    monkeypatch.setattr(public_copy, '_read_override', lambda _: json.dumps({
        'text': {'seo.title': replacement}, 'base': {'seo.title': digest(original['text']['seo.title'])},
    }))
    result = public_copy.copy_for_public_view('home', raw)
    assert result == re.sub(r'<title>.*?</title>', '<title>Synthetic title &amp; option</title>', raw, count=1)
    drifted = raw.replace('class="land-how ', 'class="synthetic-new-section ', 1)
    assert drifted != raw
    assert public_copy.copy_for_public_view('home', drifted) == drifted
    changed_title = re.sub(r'<title>.*?</title>', '<title>Synthetic new baseline</title>', raw, count=1)
    assert public_copy.copy_for_public_view('home', changed_title) == changed_title

    def unexpected_markup(*args: object, **kwargs: object) -> str:
        pytest.fail('The original fast path must skip markup processing')

    monkeypatch.setattr(public_copy, '_read_override', lambda _: None)
    monkeypatch.setattr(public_copy, 'apply_copy', unexpected_markup)
    assert public_copy.copy_for_public_view('home', raw) is raw


def test_two_first_publications_lock_the_missing_setting(app: Flask) -> None:
    engine = db.engine
    if engine.dialect.name != 'postgresql':
        pytest.skip('Requires independent PostgreSQL transactions')
    admin = User(username='public_copy_parallel', email='public-copy@example.invalid',
                 is_admin=True, active=True, onboarding_completed=True)
    admin.set_password('synthetic local test only')
    db.session.add(admin)
    db.session.commit()
    admin_id, login_id = admin.id, admin.get_id()
    url = PAGES + '/support'
    marker = Event()
    barrier = Barrier(2, action=marker.set)

    def await_lock(
        connection: Connection, cursor: Any, statement: str, parameters: Any,
        context: ExecutionContext, executemany: bool,
    ) -> None:
        if 'pg_advisory_xact_lock' in statement:
            barrier.wait(timeout=8)

    def submit(title: str) -> int:
        with app.app_context():
            client = app.test_client()
            with client.session_transaction() as session:
                session['_user_id'] = login_id
                session['_fresh'] = True
            inputs = _form(_page(client.get(url)))
            inputs['text.1.1'] = title
            inputs['action'] = 'preview'
            draft = client.post(url, data=inputs)
            assert draft.status_code == 200
            publish = _form(_page(draft))
            publish['action'] = 'publish'
            return client.post(url, data=publish).status_code

    assert db.session.get(SiteSettings, 'public_copy.support') is None
    event.listen(engine, 'before_cursor_execute', await_lock)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            requests = [executor.submit(submit, title) for title in ('Synthetic A', 'Synthetic B')]
            assert sorted(future.result(timeout=12) for future in requests) == [303, 409]
        assert marker.is_set()
        assert AdminAuditLog.query.filter_by(admin_id=admin_id, action='public_copy.publish.support').count() == 1
        page = _as_guest(app.test_client(), '/support/mobile')
        assert page.select_one('h1').get_text(strip=True) in ('Synthetic A', 'Synthetic B')
    finally:
        event.remove(engine, 'before_cursor_execute', await_lock)
        db.session.rollback()
        AdminAuditLog.query.filter_by(admin_id=admin_id).delete()
        SiteSettings.query.filter_by(key='public_copy.support').delete()
        User.query.filter_by(id=admin_id).delete()
        db.session.commit()
