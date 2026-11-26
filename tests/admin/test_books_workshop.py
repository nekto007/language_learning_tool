"""Exercise the book import, publication and reader through their entry points."""


from datetime import datetime
from gzip import decompress
from io import BytesIO
from json import loads
from pathlib import Path
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup
from docx import Document
from ebooklib import epub
from flask import Flask, g
from flask.testing import FlaskClient
from flask_jwt_extended import create_access_token
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy.orm import scoped_session

from app.admin.audit import AdminAuditLog
from app.admin.routes import book_routes
from app.admin.services.book_import import import_chapters
from app.admin.services.book_processing_service import BookProcessingService
from app.admin.utils import import_helpers
from app.auth.models import User
from app.books.models import Book, Bookmark, Chapter, UserChapterProgress
from app.curriculum.book_courses import BookCourse, BookCourseEnrollment
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.snapshot import _reading_book_unreachable
from app.study.models import StudySettings
from app.utils.db import db


@pytest.fixture
def isolated_import(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Mock:
    worker = Mock()
    monkeypatch.setattr(BookProcessingService, 'start_background_chapter_processing', worker)
    monkeypatch.setattr(import_helpers, 'IMPORT_TEMP_DIR', str(tmp_path))
    return worker


def _book(session: scoped_session, *, published: bool = True, **kwargs: object) -> Book:
    book = Book(title='Synthetic story', author='Test author', level='A1', chapters_cnt=9,
                is_published=published, rights_status='public_domain', **kwargs)
    session.add(book)
    session.flush()
    return book


def _login(app: Flask, user: User) -> FlaskClient:
    user.onboarding_completed = True
    g.pop('_login_user', None)
    client = app.test_client()
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['user_id'] = user.id
        session['_fresh'] = True
    return client


def test_epub_uses_spine_and_preserves_preface_and_subheading(tmp_path: Path) -> None:
    book = epub.EpubBook()
    book.set_title('Synthetic anthology')
    book.set_identifier('test-synthetic')
    book.set_language('en')
    preface = epub.EpubHtml(title='Preface', file_name='intro.xhtml', content='<h1>Preface</h1><p>My preface.</p>')
    second = epub.EpubHtml(title='Second', file_name='second.xhtml',
                           content='<div class="chapter"><h2>Second story</h2><p>Second body.</p></div>')
    first = epub.EpubHtml(title='First', file_name='first.xhtml', content=(
        '<div class="chapter"><h2>First story</h2><p>First body.</p><h3>II.</h3><p>Still the first.</p></div>'
    ))
    for item in (preface, second, first):
        book.add_item(item)
    book.add_item(epub.EpubNcx())
    book.spine = [preface, first, second]
    path = tmp_path / 'test.epub'
    epub.write_epub(str(path), book)
    chapters = import_chapters(path, '.epub', '', 'Synthetic anthology')
    assert len(chapters) == 3
    assert chapters[0].title == 'Preface' and chapters[0].text == 'My preface.'
    assert chapters[1].title == 'First story'
    assert chapters[1].text == 'First body.\n\nII.\n\nStill the first.'
    assert chapters[2].title == 'Second story'


def test_epub_uses_named_parts_and_keeps_unmarked_continuation(tmp_path: Path) -> None:
    book = epub.EpubBook()
    book.set_title('Stories')
    book.set_identifier('test-named-spine')
    book.set_language('en')
    first = epub.EpubHtml(title='First', file_name='first.xhtml', content=(
        '<div id="pg-header">Publisher wrapper</div>'
        '<h2 id="morning">A New Morning</h2><p>We are h<em>er</em>e.<br/>It starts soon.</p>'
        '<h2 id="later">Later That Day</h2><p>The scene continues.</p>'
    ))
    continuation = epub.EpubHtml(title='Continuation', file_name='continued.xhtml',
                                 content='<p>The ending remains in the second part.</p>')
    for item in (first, continuation, epub.EpubNcx()):
        book.add_item(item)
    book.spine = [first, continuation]
    book.toc = [epub.Link('first.xhtml#morning', 'A New Morning', 'morning'),
                epub.Link('first.xhtml#later', 'Later That Day', 'later')]
    path = tmp_path / 'named.epub'
    epub.write_epub(str(path), book)
    chapters = import_chapters(path, '.epub', '', 'Stories')
    assert [chapter.title for chapter in chapters] == ['A New Morning', 'Later That Day']
    assert chapters[0].text == 'We are here.\n\nIt starts soon.'
    assert chapters[1].text.endswith('The ending remains in the second part.')


def test_existing_file_formats_produce_readable_text(tmp_path: Path) -> None:
    fb2 = tmp_path / 'story.fb2'
    fb2.write_text('<FictionBook><body><section><title><p>One</p></title>'
                   '<p>A small <emphasis>story</emphasis>.</p></section></body></FictionBook>')
    assert import_chapters(fb2, '.fb2', '', 'Test')[0].text == 'A small story.'

    docx = tmp_path / 'story.docx'
    document = Document()
    document.add_paragraph('A small story.')
    document.save(str(docx))
    assert import_chapters(docx, '.docx', '', 'Test')[0].text == 'A small story.'

    pdf = tmp_path / 'story.pdf'
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({
        NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
        NameObject('/BaseFont'): NameObject('/Helvetica'),
    })
    page[NameObject('/Resources')] = DictionaryObject({
        NameObject('/Font'): DictionaryObject({NameObject('/F1'): font}),
    })
    content = DecodedStreamObject()
    content.set_data(b'BT /F1 12 Tf 20 250 Td (A small story.) Tj ET')
    page.replace_contents(content)
    writer.write(pdf)
    assert import_chapters(pdf, '.pdf', '', 'Test')[0].text == 'A small story.'


def test_add_then_publish_and_keep_progress_on_duplicate(
    app: Flask, admin_user: User, test_user: User, db_session: scoped_session, isolated_import: Mock,
) -> None:
    admin_client = _login(app, admin_user)
    title = 'Test booklet'
    form = {'title': title, 'author': 'Test', 'level': 'C2', 'rights_status': 'public_domain'}
    source = b'CHAPTER I.\n\nA calm afternoon.\n\nCHAPTER II.\n\nThe story ends.'
    response = admin_client.post('/admin/books/add', data={**form, 'file': (BytesIO(source), 'test.txt')})
    assert response.status_code == 303
    book = Book.query.filter_by(title=title).one()
    assert book.level == 'C2'
    assert title.encode() in admin_client.get('/admin/books?level=C2').data
    student = _login(app, test_user)
    assert student.get(f'/books/{book.id}').status_code == 404
    g.pop('_login_user', None)
    assert b'A calm afternoon' in admin_client.get(f'/read/{book.id}/chapters?preview=learner').data
    assert admin_client.post(f'/admin/books/{book.id}/publication', data={'action': 'publish'}).status_code == 303
    g.pop('_login_user', None)
    assert b'A calm afternoon' in student.get(f'/read/{book.id}', follow_redirects=True).data
    chapter = book.chapters[0]
    progress = UserChapterProgress(user_id=test_user.id, chapter_id=chapter.id, offset_pct=.4)
    db_session.add(progress)
    db_session.commit()

    g.pop('_login_user', None)
    replacement = admin_client.post('/admin/books/add', data={**form, 'content': 'Other', 'overwrite': 'true'})
    assert replacement.status_code == 409
    assert chapter.text_raw == 'A calm afternoon.'
    assert db_session.get(UserChapterProgress, (test_user.id, chapter.id)).offset_pct == .4
    assert AdminAuditLog.query.filter_by(action='book.create', target_id=book.id).count() == 1
    assert isolated_import.call_count == 1
    assert admin_client.post(f'/admin/books/{book.id}/publication', data={'action': 'unpublish'}).status_code == 303
    g.pop('_login_user', None)
    assert student.get(f'/books/{book.id}/read').status_code == 404


def test_empty_and_audit_failure_leave_no_book(
    admin_client: FlaskClient, isolated_import: Mock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    form = {'title': 'Import rollback fixture'}
    assert admin_client.post('/admin/books/add', data=form).status_code == 422
    assert admin_client.post('/admin/books/add', data={**form, 'file': (BytesIO(b'not an epub'), 'bad.epub')}).status_code == 422
    audit = Mock(side_effect=RuntimeError('audit unavailable'))
    monkeypatch.setattr(book_routes, 'log_admin_action', audit)
    assert admin_client.post('/admin/books/add', data={**form, 'content': 'A readable story.'}).status_code == 500
    assert Book.query.filter_by(title=form['title']).count() == 0
    assert not isolated_import.called
    assert audit.call_args.kwargs['required']


def test_old_book_attachment_requires_preview_and_preserves_identity(
    app: Flask, admin_user: User, db_session: scoped_session, isolated_import: Mock,
) -> None:
    admin_client = _login(app, admin_user)
    book = _book(db_session, published=False, summary='Existing summary', created_at=datetime(2020, 1, 1))
    db_session.commit()
    url = f'/admin/books/{book.id}/text'
    assert admin_client.get(f'/content/{book.id}').location == url
    assert f'data-book-id="{book.id}"'.encode() in admin_client.get('/admin/books?text=missing').data
    assert admin_client.post(f'/content/{book.id}', data={'content': 'Legacy submit'}).status_code == 303
    assert not book.chapters
    assert admin_client.post(url, data={'action': 'apply'}).status_code == 409
    preview = admin_client.post(url, data={'action': 'preview', 'content': 'New text.'})
    token = BeautifulSoup(preview.data, 'html.parser').select_one('[name=preview_token]')['value']
    assert not book.chapters
    payload = {'action': 'apply', 'preview_token': token}
    assert admin_client.post(url, data=payload).status_code == 303
    assert admin_client.post(url, data=payload).status_code == 409
    db_session.refresh(book)
    assert book.summary == 'Existing summary' and not book.is_published and book.created_at.year == 2020
    assert [chapter.text_raw for chapter in book.chapters] == ['New text.']
    assert AdminAuditLog.query.filter_by(action='book.text.attach', target_id=book.id).count() == 1


@pytest.mark.parametrize('percent', [0, 35, 100])
def test_reader_applies_percent_on_both_web_and_api_entries(
    app: Flask, admin_user: User, db_session: scoped_session, test_user: User, percent: int,
) -> None:
    text = 'It starts here. ' * 8 + 'Hidden ending.'
    book = _book(db_session, is_free_access=True, allowed_text_percent=percent)
    book.rights_status = 'licensed'
    book.chapters.append(Chapter(chap_num=1, title='Chapter', text_raw=text, words=25))
    db_session.commit()
    student = _login(app, test_user)
    chapter_id = book.chapters[0].id
    chapter = f'/api/books/{book.id}/chapters/1'
    response = student.get(chapter, headers={'Accept-Encoding': 'gzip'})
    chapter_data = loads(decompress(response.data))
    actual = chapter_data['text']
    by_id = student.get(f'/api/chapters/{chapter_id}').json['chapter']
    assert actual == by_id['text_raw']
    assert chapter_data['text_truncated'] is (percent < 100)
    assert by_id['text_truncated'] is (percent < 100)
    if percent == 0:
        assert actual == ''
    elif percent == 100:
        assert actual == text
    else:
        assert 0 < len(actual) <= len(text) * percent / 100
        assert text.startswith(actual)
    for path in (f'/read/{book.id}/chapters', f'/books/{book.id}/read'):
        assert BeautifulSoup(student.get(path).data, 'html.parser').select_one('#chapterContent').get_text(strip=True) == actual
    admin_client = _login(app, admin_user)
    preview = admin_client.get(f'/read/{book.id}/chapters?preview=learner')
    assert BeautifulSoup(preview.data, 'html.parser').select_one('#chapterContent').get_text(strip=True) == actual
    admin_chapter = admin_client.get(chapter).json
    admin_by_id = admin_client.get(f'/api/chapters/{chapter_id}').json['chapter']
    assert admin_chapter['text'] == admin_by_id['text_raw'] == text
    assert admin_chapter['text_truncated'] is admin_by_id['text_truncated'] is False
    assert admin_client.post(f'/admin/books/{book.id}/edit', data={'title': 'Edited metadata', 'level': 'C2'}).status_code == 302
    db_session.refresh(book)
    assert book.allowed_text_percent == percent and book.level == 'C2'


def test_legacy_slot_cannot_require_a_zero_text_edition(db_session: scoped_session, test_user: User) -> None:
    book = _book(db_session, allowed_text_percent=0, is_free_access=True)
    book.rights_status = 'licensed'
    book.chapters.append(Chapter(chap_num=1, title='Chapter', text_raw='A text.', words=2))
    db_session.commit()
    assert _reading_book_unreachable(test_user.id, {'kind': 'reading', 'data': {'book_id': book.id}}, db)


def test_unreadable_selection_preserves_current_book_and_goal(
    app: Flask, db_session: scoped_session, test_user: User,
) -> None:
    selected = _book(db_session)
    selected.chapters.append(Chapter(chap_num=1, title='Original', text_raw='My selected book.', words=3))
    blank = _book(db_session)
    blank.chapters.append(Chapter(chap_num=1, title='Blank', text_raw=' \\n\t ', words=0))
    zero = _book(db_session, allowed_text_percent=0, is_free_access=True)
    zero.rights_status = 'licensed'
    zero.chapters.append(Chapter(chap_num=1, title='Restricted', text_raw='No excerpt allowed.', words=3))
    pref = UserReadingPreference(user_id=test_user.id, book_id=selected.id)
    settings = StudySettings(user_id=test_user.id, reading_minutes_per_day=13)
    db_session.add_all([pref, settings])
    db_session.commit()

    student = _login(app, test_user)
    choices = student.get('/api/books/catalog?level=A1').json['books']
    ids = {entry['id'] for entry in choices}
    assert selected.id in ids and blank.id not in ids and zero.id not in ids
    bearer = create_access_token(str(test_user.id), additional_claims={'auth_version': test_user.auth_version()})
    for book in (blank, zero):
        for route, headers in (
            ('/api/books/select', {}),
            ('/api/native/books/select', {'Authorization': f'Bearer {bearer}'}),
        ):
            response = student.post(route, headers=headers, json={'book_id': book.id})
            assert response.status_code == 409
            assert response.json['error'] == 'book_not_readable'
        db_session.refresh(pref)
        db_session.refresh(settings)
        assert pref.book_id == selected.id and settings.reading_minutes_per_day == 13


def test_book_course_links_follow_existing_visibility_without_enrolling(
    app: Flask, db_session: scoped_session, test_user: User,
) -> None:
    book = _book(db_session)
    open_course = BookCourse(book_id=book.id, title='Read with a course', level='A1', is_active=True)
    closed_course = BookCourse(book_id=book.id, title='Hidden course', level='A1', is_active=False)
    other = _book(db_session)
    db_session.add_all([open_course, closed_course])
    db_session.commit()

    student = _login(app, test_user)
    course_url = f'/curriculum/book-courses/{open_course.id}'
    book_url = f'/books/{book.id}'

    def links(url: str) -> set[str]:
        response = student.get(url)
        assert response.status_code == 200
        return {link['href'] for link in BeautifulSoup(response.data, 'html.parser').select('a[href]')}

    assert course_url in links(book_url)
    assert f'/curriculum/book-courses/{closed_course.id}' not in links(book_url)
    assert course_url not in links(f'/books/{other.id}')
    assert book_url in links(course_url)
    assert BookCourseEnrollment.query.filter_by(user_id=test_user.id).count() == 0
    book.rights_status = 'companion_only'
    db_session.commit()
    assert book_url not in links(course_url)
    book.is_published = False
    db_session.commit()
    assert student.get(course_url).status_code == 404
    assert student.get(book_url).status_code == 404


def test_delete_requires_confirmation_and_protects_bookmark(
    admin_client: FlaskClient, db_session: scoped_session, test_user: User,
) -> None:
    book = _book(db_session, published=False)
    url = f'/admin/books/{book.id}/delete'
    bookmark = Bookmark(book_id=book.id, user_id=test_user.id, name='Keep this reference')
    db_session.add(bookmark)
    db_session.commit()
    assert admin_client.post(url, data={'confirm': 'yes'}).status_code == 409
    assert db_session.get(Book, book.id) is not None
    db_session.delete(bookmark)
    db_session.commit()
    assert admin_client.post(url).status_code == 400
    assert admin_client.post(url, data={'confirm': 'yes'}).status_code == 303
