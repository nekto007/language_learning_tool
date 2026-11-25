"""Browser route regressions for administrative publication using synthetic material."""

import io
import json
import random
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import pytest
from flask import Flask, g
from flask.testing import FlaskClient
from sqlalchemy.orm import scoped_session

from app.admin.audit import AdminAuditLog
from app.admin.utils import import_helpers
from app.auth.models import User
from app.books.models import Book, Bookmark, Chapter, UserChapterProgress
from app.onboarding.placement_bank import activate_bank, active_bank
from app.onboarding.placement_models import PlacementAttempt, PlacementBank
from tests.admin.test_materials import _page
from tests.api.test_grammar_lab_disputes import browser
from tests.placement_fixtures import synthetic_bank
from tests.short_reading_fixtures import write_pack

BANK = '/admin/placement-bank'
PLACEMENT = '/onboarding/placement/v2'


def _form_values(page: BeautifulSoup, marker: str) -> dict[str, str]:
    form = page.select_one(marker).find_parent('form')
    data = {}
    for field in form.select('input[name], textarea[name], select[name]'):
        if field.name == 'select':
            selected = field.select_one('option[selected]') or field.select_one('option')
            value = selected.get('value', selected.get_text())
        elif field.name == 'textarea':
            value = field.get_text()
        else:
            value = field.get('value', '')
        data[field['name']] = value
    return data


def test_short_reading_publication_repairs_legacy_key_and_keeps_reader_history(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session, tmp_path: Path,
) -> None:
    item = json.loads(write_pack(tmp_path / 'synthetic.json').read_text())['items'][0]
    reading = item['reading']
    reading['order'] = 37
    reading['questions'][0]['correct_option'] = 'obsolete'
    book = Book(slug='synthetic-other-reading', title=item['title'], author='Test', level='A1', chapters_cnt=1,
                reading=reading, summary=reading['focus'], rights_status='public_domain')
    db_session.add(book)
    db_session.flush()
    chapter = Chapter(book_id=book.id, chap_num=1, title='Synthetic chapter', text_raw=item['text'], words=44)
    db_session.add(chapter)
    db_session.flush()
    bookmark = Bookmark(user_id=test_user.id, book_id=book.id, name='Reader note', context='Fixture Fixture', position=24)
    progress = UserChapterProgress(user_id=test_user.id, chapter_id=chapter.id, offset_pct=0.42)
    db_session.add_all([bookmark, progress])
    db_session.commit()
    editor_url = f'/admin/books/{book.id}/short-reading'
    page = _page(admin_client.get(editor_url))
    body = _form_values(page, '[name=revision]')
    body.update(text=item['text'].replace('Fixture', 'Sample', 1), g0_translation='New translation',
                q0_correct_option='a', focus='Revised focus.', estimated_minutes='6', action='preview')
    assert admin_client.post(editor_url, data={**body, 'q0_correct_option': 'unknown'}).status_code == 422
    prepared = admin_client.post(editor_url, data=body)
    assert prepared.status_code == 200
    preview = _page(prepared)
    assert all(value in preview.text for value in ('Revised focus.', 'New translation', 'Fixture option a.'))
    assert book.reading['questions'][0]['correct_option'] == 'obsolete'
    assert chapter.text_raw == item['text']
    publish = {**body, 'action': 'apply', 'preview_token': preview.select_one('[name=preview_token]')['value']}
    assert admin_client.post(editor_url, data={**publish, 'estimated_minutes': '9'}).status_code == 409
    assert admin_client.post(editor_url, data=publish).status_code == 303
    assert admin_client.post(editor_url, data=publish).status_code == 409
    assert book.reading['order'] == 37
    assert book.reading['focus'] == book.summary == 'Revised focus.'
    assert book.reading['estimated_minutes'] == 6
    assert book.reading['glossary'][0]['translation'] == 'New translation'
    assert [(q['id'], q['correct_option']) for q in book.reading['questions']] == [('q1', 'a'), ('q2', 'b')]
    assert bookmark.context == 'Fixture Fixture' and bookmark.position == 24 and progress.offset_pct == 0.42
    assert progress.chapter_id == chapter.id
    assert AdminAuditLog.query.filter_by(action='book.short_reading.publish', target_id=str(book.id)).count() == 1
    reader, _ = browser(app, test_user)
    g.pop('_login_user', None)
    response = reader.get(f'/api/books/{book.id}/chapters/1')
    assert response.status_code == 200 and response.json['text'] == body['text']
    assert reader.get(f'/books/{book.slug}/chapter/1').status_code == 200


def _start(client: FlaskClient) -> dict:
    g.pop('_login_user', None)
    result = client.post(f'{PLACEMENT}/start', json={'mode': 'quick'})
    assert result.status_code == 200
    attempt = result.json['attempt']
    assert not {'answer', 'answers', 'correct'} & attempt['question'].keys()
    return attempt


def _answer(client: FlaskClient, attempt: dict, value: str) -> None:
    g.pop('_login_user', None)
    result = client.post(f"{PLACEMENT}/{attempt['id']}/answer", json={
        'question_id': attempt['question']['id'], 'answer': value, 'dont_know': False,
    })
    assert result.status_code == 200
    assert result.json['attempt']['answered'] == 1


def test_question_publish_preserves_guest_and_member_attempts_and_filter_context(
    app: Flask, admin_client: FlaskClient, test_user: User, db_session: scoped_session, tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(import_helpers, 'IMPORT_TEMP_DIR', str(tmp_path))
    monkeypatch.setattr(random.SystemRandom, 'choice', lambda _, choices: choices[0])
    document = synthetic_bank()
    old_id, _ = activate_bank(document)
    db_session.commit()
    guest = app.test_client()
    member, _ = browser(app, test_user)
    g.pop('_login_user', None)
    assert guest.get('/placement').status_code == 200
    guest_old, member_old = _start(guest), _start(member)
    item = document['items'][0]
    g.pop('_login_user', None)
    params = {'q': 'Synthetic', 'level': item['level'], 'skill': item['skill'], 'page': '1'}
    listing = _page(admin_client.get(BANK, query_string=params))
    edit_url = listing.select_one(f'a[href*="/questions/{item["id"]}?"]')['href']
    form = _page(admin_client.get(edit_url))
    back = form.find('a', string='Вернуться к списку вопросов')['href']
    assert parse_qs(urlsplit(back).query) == {key: [value] for key, value in params.items()}
    data = _form_values(form, '[name=bank_id]')
    data.update(prompt='Synthetic changed question', answers='Wrong answer')
    staged = admin_client.post(edit_url, data=data)
    assert staged.status_code == 303
    preview_response = admin_client.get(staged.location)
    assert preview_response.status_code == 200 and preview_response.headers['Cache-Control'] == 'private, no-store'
    preview = _page(preview_response)
    assert 'Synthetic changed question' in preview.text and 'Wrong answer' in preview.text
    assert preview.find('a', string='Вернуться к списку вопросов')['href'] == back
    assert active_bank().id == old_id
    assert [file.stat().st_mode & 0o777 for file in tmp_path.glob('private-placement-*.json')] == [0o600]
    activation = _form_values(preview, '[name=preview_id]')
    saved = admin_client.post(f'{BANK}/activate', data=activation)
    assert saved.status_code == 303 and saved.location == back
    new_id = active_bank().id
    assert new_id != old_id
    assert db_session.get(PlacementBank, old_id).content['items'][0]['answers'] == ['A correct answer']
    assert active_bank().content['items'][0]['answers'] == ['Wrong answer']
    assert AdminAuditLog.query.filter_by(action='placement.bank.activate').count() == 1
    for client, original in ((guest, guest_old), (member, member_old)):
        attempt = db_session.get(PlacementAttempt, original['id'])
        assert attempt.bank_id == old_id and attempt.state['asked'][0]['id'] == item['id']
        _answer(client, original, 'A correct answer')
        assert attempt.state['asked'][0]['correct']
    new_guest = app.test_client()
    g.pop('_login_user', None)
    assert new_guest.get('/placement').status_code == 200
    started = _start(new_guest)
    attempt = db_session.get(PlacementAttempt, started['id'])
    assert attempt.bank_id == new_id and attempt.state['asked'][0]['id'] == item['id']
    _answer(new_guest, started, 'Wrong answer')
    assert attempt.state['asked'][0]['correct']
    g.pop('_login_user', None)
    denied = member.get(edit_url)
    assert denied.status_code in (302, 403) and 'Synthetic changed question' not in denied.text


def test_bank_upload_pages_cover_all_keys_and_stale_activation_keeps_winner(
    admin_client: FlaskClient, db_session: scoped_session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(import_helpers, 'IMPORT_TEMP_DIR', str(tmp_path))
    document = synthetic_bank()
    uploaded = admin_client.post(f'{BANK}/upload', data={
        'bank': (io.BytesIO(json.dumps(document).encode()), 'synthetic.json'),
    })
    assert uploaded.status_code == 303
    assert active_bank() is None
    preview_url = uploaded.location
    first = _page(admin_client.get(preview_url))
    assert document['items'][0]['id'] in first.text and document['items'][-1]['id'] not in first.text
    found = []
    page = first
    while True:
        found.extend(node.get_text(strip=True) for node in page.select('details.mb-2 > summary'))
        link = page.find('a', string='Следующая')
        if link is None:
            break
        page = _page(admin_client.get(link['href']))
    assert found == [item['id'] for item in document['items']]
    assert 'A correct answer' in page.text
    winner, _ = activate_bank({**document, 'label': 'Concurrent bank'})
    db_session.commit()
    assert admin_client.post(f'{BANK}/activate', data=_form_values(first, '[name=preview_id]')).status_code == 409
    assert active_bank().id == winner
    assert AdminAuditLog.query.filter_by(action='placement.bank.activate').count() == 0
    invalid = admin_client.post(f'{BANK}/upload', data={
        'bank': (io.BytesIO(b'{"items": [], "items": []}'), 'invalid.json'),
    })
    assert invalid.status_code == 303 and invalid.location == BANK
    revised = admin_client.post(f'{BANK}/upload', data={
        'bank': (io.BytesIO(json.dumps(document).encode()), 'synthetic.json'),
    })
    preview = _page(admin_client.get(revised.location))
    form = _form_values(preview, '[name=preview_id]')
    assert admin_client.post(f'{BANK}/activate', data=form).status_code == 303
    assert active_bank().content == document
    assert admin_client.post(f'{BANK}/activate', data=form).status_code == 303
    assert AdminAuditLog.query.filter_by(action='placement.bank.activate').count() == 1


def test_admin_account_deletion_queue_is_available_before_onboarding(
    admin_client: FlaskClient, admin_user: User, db_session: scoped_session,
) -> None:
    admin_user.onboarding_completed = False
    db_session.commit()
    page = admin_client.get('/admin/account-deletions')
    assert page.status_code == 200
    assert _page(page).select_one('#sidebar a[href="/admin/account-deletions"]')
    assert admin_client.post('/admin/account-deletions/missing/complete').status_code == 409
