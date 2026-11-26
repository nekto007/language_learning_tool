"""Additive course links on the real catalog and account-library routes."""

import json
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup
from flask import Flask, g, url_for
from flask.testing import FlaskClient
from flask_jwt_extended import create_access_token
from sqlalchemy import event
from sqlalchemy.orm import scoped_session

from app.auth.models import User
from app.books.models import Book, Chapter, UserChapterProgress
from app.curriculum.book_courses import BookCourse, BookCourseEnrollment, BookCourseModule, BookModuleProgress
from app.daily_plan.linear.models import UserReadingPreference
from app.utils.db import db
from tests.api.test_books_catalog import cefr_levels as cefr_levels
from tests.api.test_course_receipt_expiry import sign_in

CATALOG = '/api/books/catalog'
pytestmark = pytest.mark.usefixtures('cefr_levels')


def _book(session: scoped_session, title: str, *, level: str = 'A1', **values: Any) -> tuple[Book, Chapter]:
    book = Book(title=title, author='Synthetic author', level=level, chapters_cnt=1,
                rights_status='public_domain', **values)
    session.add(book)
    session.flush()
    chapter = Chapter(book_id=book.id, chap_num=1, title='First chapter', words=2, text_raw='Synthetic text.')
    session.add(chapter)
    session.flush()
    return book, chapter


def _course(session: scoped_session, book: Book, title: str, *, active: bool = True) -> BookCourse:
    course = BookCourse(book_id=book.id, title=title, level=book.level, is_active=active)
    session.add(course)
    session.flush()
    return course


def _catalog(client: FlaskClient, account: User, *, history: bool = False) -> dict:
    token = create_access_token(identity=str(account.id), additional_claims={'auth_version': account.auth_version()})
    arguments = {'level': 'A1', 'include_library': '1'} if history else {'level': 'A1'}
    response = client.get(CATALOG, query_string=arguments, headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'private, no-store'
    return response.json


def _href(course: BookCourse) -> str:
    with_path = url_for('book_courses.view_course', course_id=course.id)
    assert with_path == f'/curriculum/book-courses/{course.id}' and not urlsplit(with_path).netloc
    return with_path


def test_catalog_course_links_order_visibility_and_web_profile(
    app: Flask, db_session: scoped_session, test_user: User, admin_user: User, tmp_path: Path,
) -> None:
    none, _ = _book(db_session, 'Unlinked title')
    paired, paired_chapter = _book(db_session, 'Two courses')
    licensed, _ = _book(db_session, 'Publisher-access title', is_free_access=True)
    licensed.rights_status = 'licensed'
    blocked, blocked_chapter = _book(db_session, 'Expired title', expiration_date=date(2000, 1, 1), is_free_access=True)
    blocked.rights_status = 'licensed'
    draft, draft_chapter = _book(db_session, 'Draft title', is_published=False)
    historical, historical_chapter = _book(db_session, 'History outside window', level='B2')
    first = _course(db_session, paired, 'Z course')
    inactive = _course(db_session, paired, 'Inactive course', active=False)
    second = _course(db_session, paired, 'A course')
    free = _course(db_session, licensed, 'Licensed course')
    hidden = _course(db_session, blocked, 'Expired access course')
    draft_course = _course(db_session, draft, 'Draft access course')
    history_course = _course(db_session, historical, 'History course')
    module = BookCourseModule(course_id=first.id, module_number=1, title='Synthetic module')
    enrolled = User(username='site51-enrolled', email='site51-enrolled@example.invalid', active=True,
                    onboarding_completed=True, onboarding_level='A1', timezone='UTC')
    enrolled.set_password('site51-synthetic')
    db_session.add_all([module, enrolled])
    admin_user.onboarding_completed = True
    db_session.flush()
    enrollment = BookCourseEnrollment(user_id=enrolled.id, course_id=first.id, current_module_id=module.id,
                                      progress_percentage=37)
    db_session.add(enrollment)
    db_session.flush()
    module_progress = BookModuleProgress(enrollment_id=enrollment.id, module_id=module.id, progress_percentage=40)
    readings = [UserChapterProgress(user_id=enrolled.id, chapter_id=chapter.id, offset_pct=0.35)
                for chapter in (paired_chapter, historical_chapter, blocked_chapter, draft_chapter)]
    readings.append(UserChapterProgress(user_id=admin_user.id, chapter_id=draft_chapter.id, offset_pct=0.5))
    preference = UserReadingPreference(user_id=enrolled.id, book_id=historical.id)
    db_session.add_all([module_progress, preference, *readings])
    db_session.commit()

    def state() -> tuple:
        return (
            [(r.id, r.user_id, r.course_id, r.progress_percentage, r.last_activity)
             for r in BookCourseEnrollment.query.order_by(BookCourseEnrollment.id)],
            [(r.id, r.progress_percentage, r.last_activity) for r in BookModuleProgress.query],
            [(r.user_id, r.chapter_id, r.offset_pct, r.updated_at)
             for r in UserChapterProgress.query.order_by(UserChapterProgress.user_id, UserChapterProgress.chapter_id)],
            [(r.user_id, r.book_id, r.selected_at) for r in UserReadingPreference.query],
        )

    db_session.expire_all()
    before = state()
    with app.test_request_context():
        first_path, second_path, free_path, history_path = map(_href, (first, second, free, history_course))
        hidden_paths = list(map(_href, (inactive, hidden, draft_course)))
    wants = {
        none.id: [],
        paired.id: [{'title': first.title, 'path': first_path}, {'title': second.title, 'path': second_path}],
        licensed.id: [{'title': free.title, 'path': free_path}],
    }
    no_history = _catalog(app.test_client(), test_user)
    assert 'library_books' not in no_history
    freshman = _catalog(app.test_client(), test_user, history=True)
    assert freshman['library_books'] == [] and freshman['books'] == no_history['books']
    data = _catalog(app.test_client(), enrolled, history=True)
    assert data['books'] == no_history['books']
    catalog = {row['id']: row for row in data['books']}
    history = {row['book']['id']: row for row in data['library_books']}
    assert set(catalog) >= set(wants)
    assert {bid: catalog[bid]['book_courses'] for bid in wants} == wants
    assert set(history) == {paired.id, historical.id}
    assert history[paired.id]['book']['book_courses'] == wants[paired.id]
    assert history[historical.id]['book']['book_courses'] == [{'title': history_course.title, 'path': history_path}]
    assert history[paired.id]['progress']['offset_pct'] == 0.35
    assert blocked.id not in catalog and draft.id not in catalog and historical.id not in catalog
    assert all(path not in json.dumps(data) for path in hidden_paths)
    admin_catalog = _catalog(app.test_client(), admin_user, history=True)
    admin_history = {row['book']['id']: row['book']['book_courses'] for row in admin_catalog['library_books']}
    assert admin_history[draft.id] == []

    g.pop('_login_user', None)
    unauthenticated = app.test_client().get(first_path)
    assert unauthenticated.status_code == 302 and urlsplit(unauthenticated.location).path == '/login'
    assert first_path in unauthenticated.location
    for account in (test_user, enrolled):
        web = app.test_client()
        sign_in(web, app, account)
        # The normal book page and compact/mobile template use the same order.
        for args in ({}, {'optimized': 'false'}):
            page = web.get(f'/books/{paired.id}', query_string=args)
            assert page.status_code == 200
            links = BeautifulSoup(page.data, 'html.parser').select('a[href^="/curriculum/book-courses/"]')
            assert [link['href'] for link in links] == [first_path, second_path]
        for path in (first_path, second_path, free_path, history_path):
            response = web.get(path)
            assert response.status_code == 200
        detail = BeautifulSoup(web.get(first_path).data, 'html.parser')
        assert bool(detail.select_one('#enroll-btn')) == (account.id == test_user.id)
        assert bool(detail.select_one('a.cd-hero__cta[href]')) == (account.id == enrolled.id)
    db_session.expire_all()
    assert state() == before
    (tmp_path / 'catalog-fresh.json').write_text(json.dumps(no_history, ensure_ascii=False) + '\n')
    (tmp_path / 'catalog-history.json').write_text(json.dumps(data, ensure_ascii=False) + '\n')


@pytest.mark.parametrize('history', [False, True])
def test_batched_course_link_query_stays_constant(
    app: Flask, db_session: scoped_session, test_user: User, history: bool, tmp_path: Path,
) -> None:

    def add(index: int) -> None:
        book, chapter = _book(db_session, f'Synthetic query sample {index}')
        _course(db_session, book, f'Course {index}')
        db_session.add(UserChapterProgress(user_id=test_user.id, chapter_id=chapter.id, offset_pct=0.1))
        db_session.commit()

    client = app.test_client()

    def measure() -> tuple[int, int, int]:
        statements: list[str] = []

        def collect(_connection: Any, _cursor: Any, sql: str, *_args: Any) -> None:
            statements.append(sql.lower())

        event.listen(db.engine, 'before_cursor_execute', collect)
        try:
            response = _catalog(client, test_user, history=history)
        finally:
            event.remove(db.engine, 'before_cursor_execute', collect)
        queries = [sql for sql in statements if sql.lstrip().startswith('select')]
        course_queries = [sql for sql in queries if 'from book_courses' in sql]
        assert all('chapter.text_raw' not in sql.split('from', maxsplit=1)[0] for sql in queries)
        assert not any(sql.lstrip().startswith(('insert ', 'update ', 'delete ')) for sql in statements)
        count = sum(bool(row['book_courses']) for row in response['books'])
        return count, len(queries), len(course_queries)

    add(0)
    _catalog(client, test_user, history=history)
    one = measure()
    for index in range(1, 13):
        add(index)
    many = measure()
    assert one[0] == 1 and many[0] == 13
    assert one[1:] == many[1:] and many[2] == 1
    (tmp_path / 'query-count.json').write_text(json.dumps({'history': history, 'one': one, 'thirteen': many}) + '\n')
