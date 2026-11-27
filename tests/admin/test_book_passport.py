"""Edition previews bind the exact source and metadata without publishing."""

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
from ebooklib import epub
from flask import Flask
from flask.testing import FlaskClient
from pytest import MonkeyPatch
from sqlalchemy.orm import scoped_session

from app.admin.audit import AdminAuditLog
from app.admin.services.book_processing_service import BookProcessingService
from app.auth.models import User
from app.books.models import Book, Chapter
from tests.admin.test_books_workshop import _login


def _edition(path: Path) -> bytes:
    book = epub.EpubBook()
    book.set_identifier('test-edition-17')
    book.set_title('Synthetic Edition')
    book.add_author('Sample Author')
    book.set_language('en')
    book.add_metadata('DC', 'source', 'https://example.invalid/source/17')
    book.add_metadata('DC', 'rights', 'Publisher note for this synthetic edition')
    chapter = epub.EpubHtml(title='Opening', file_name='opening.xhtml',
                            content='<h1>Opening</h1><p>A readable fictional opening.</p>')
    book.add_item(chapter)
    book.add_item(epub.EpubNcx())
    book.spine = [chapter]
    epub.write_epub(str(path), book)
    return path.read_bytes()


def test_epub_passport_preview_checks_bytes_and_fields_before_add(
    admin_client: FlaskClient, tmp_path: Path, monkeypatch: MonkeyPatch,
) -> None:
    worker = Mock()
    monkeypatch.setattr(BookProcessingService, 'start_background_chapter_processing', worker)
    raw = _edition(tmp_path / 'edition.epub')
    extraction = admin_client.post('/admin/books/extract-metadata', data={'file': (BytesIO(raw), 'book.epub')})
    metadata = extraction.json['metadata']
    assert metadata['source_edition_id'] == 'test-edition-17'
    assert metadata['source_url'] == 'https://example.invalid/source/17'
    assert metadata['source_rights_note'] == 'Publisher note for this synthetic edition'
    assert metadata['source_format'] == 'epub'
    assert 'permission_document' not in metadata and 'rights_status' not in metadata

    payload = {'title': 'Synthetic Edition', 'author': 'Sample Author', 'passport_revision': '',
               'source_url': metadata['source_url'], 'source_edition_id': metadata['source_edition_id'],
               'permission_document': 'Editor reviewed this sample.', 'rights_status': 'companion_only'}
    before = (Book.query.count(), Chapter.query.count(), AdminAuditLog.query.count())
    preview = admin_client.post('/admin/books/add/passport-preview',
                                data={**payload, 'file': (BytesIO(raw), 'book.epub')})
    assert preview.status_code == 200
    assert preview.headers['Cache-Control'] == 'private, no-store'
    assert preview.json['values'] == {**{key: payload[key] for key in ('source_url', 'source_edition_id',
                                                                    'permission_document')},
                                      'source_format': 'epub'}
    saved = {**payload, 'passport_token': preview.json['token']}
    for override, binary in (({}, raw + b' '), ({'source_edition_id': 'other'}, raw),
                             ({'rights_status': 'public_domain'}, raw)):
        stale = admin_client.post('/admin/books/add',
                                  data={**saved, **override, 'file': (BytesIO(binary), 'book.epub')})
        assert stale.status_code == 409
        assert b'Editor reviewed this sample.' in stale.data
    assert (Book.query.count(), Chapter.query.count(), AdminAuditLog.query.count()) == before
    assert not worker.called
    response = admin_client.post('/admin/books/add', data={**saved, 'file': (BytesIO(raw), 'book.epub')})
    assert response.status_code == 303
    item = Book.query.filter_by(title=payload['title']).one()
    assert (item.source_edition_id, item.source_format) == ('test-edition-17', 'epub')
    assert (item.source_url, item.permission_document) == (payload['source_url'], payload['permission_document'])
    assert not item.is_published and item.rights_status == 'companion_only'
    assert item.chapters[0].text_raw == 'A readable fictional opening.'
    assert AdminAuditLog.query.filter_by(action='book.create', target_id=item.id).count() == 1
    assert worker.call_count == 1


def test_legacy_book_and_post_keep_passport_and_concurrent_draft(
    app: Flask, admin_user: User, test_user: User, db_session: scoped_session,
) -> None:
    item = Book(title='Older title', author='Sample Author', chapters_cnt=1,
                is_published=True, rights_status='public_domain')
    chapter = Chapter(book=item, chap_num=1, title='Opening', words=4, text_raw='A verified older chapter.')
    db_session.add_all([item, chapter])
    db_session.commit()
    path = f'/admin/books/{item.id}/edit'
    preview_path = f'/admin/books/{item.id}/passport-preview'
    reader = _login(app, test_user)
    assert b'A verified older chapter.' in reader.get(f'/read/{item.id}', follow_redirects=True).data
    admin = _login(app, admin_user)
    soup = BeautifulSoup(admin.get(path).data, 'html.parser')
    revision = soup.select_one('[name=passport_revision]')['value']
    payload = {'passport_revision': revision, 'source_edition_id': 'manual-1', 'source_format': 'epub',
               'source_url': 'https://example.invalid/one', 'permission_document': 'First reviewed edition.'}
    before = AdminAuditLog.query.count()
    preview = admin.post(preview_path, data=payload)
    other = {**payload, 'source_edition_id': 'other', 'permission_document': 'Saved independently.'}
    second = admin.post(preview_path, data=other)
    assert preview.status_code == second.status_code == 200 and item.source_edition_id is None
    assert AdminAuditLog.query.count() == before
    assert admin.post(path, data={**other, 'passport_token': second.json['token']}).status_code == 302
    assert admin.post(preview_path, data=payload).status_code == 409
    stale = admin.post(path, data={**payload, 'passport_token': preview.json['token']})
    assert stale.status_code == 409
    page = BeautifulSoup(stale.data, 'html.parser')
    assert page.select_one('#source_edition_id')['value'] == 'manual-1'
    assert page.select_one('#source_format [selected]')['value'] == 'epub'
    assert page.select_one('#permission_document').get_text() == 'First reviewed edition.'
    assert page.select_one('[name=passport_revision]')['value'] != revision
    assert page.select_one('[name=passport_token]')['value'] == ''
    assert item.source_edition_id == 'other'
    legacy = admin.post(path, data={'title': 'Updated by existing client', 'description': 'Legacy partial POST'})
    assert legacy.status_code == 302
    assert (item.source_edition_id, item.source_format) == ('other', 'epub')
    assert item.source_url == other['source_url'] and item.permission_document == other['permission_document']
    assert chapter.text_raw == 'A verified older chapter.'
    reader = _login(app, test_user)
    assert b'A verified older chapter.' in reader.get(f'/read/{item.id}', follow_redirects=True).data
