"""Exercise the repaired admin entry points against database rows."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from typing import Any

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.orm import scoped_session

from app.admin.audit import AdminAuditLog
from app.admin.services.audio_management_service import AudioManagementService
from app.auth.models import User
from app.books.models import Book
from app.curriculum.book_courses import BookCourse, BookCourseEnrollment
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db
from app.words.models import Collection, CollectionWords
from tests.admin.test_materials import _page


def _module(db_session: scoped_session, level: CEFRLevel, number: int) -> Module:
    module = Module(level=level, title=f'Synthetic module {number}', number=number)
    db_session.add(module)
    db_session.flush()
    return module


def test_create_lesson_types_conflict_and_editor(
    admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    level = CEFRLevel(code='A1', name='Synthetic level', order=1)
    first = _module(db_session, level, 1)
    second = _module(db_session, level, 2)
    book = Book(title='Synthetic book', author='Synthetic', level='A1', chapters_cnt=0)
    collection = Collection(name='Synthetic set')
    db_session.add_all([book, collection])
    db_session.commit()
    url = f'/admin/curriculum/lessons/create?module_id={first.id}'
    form_response = admin_client.get(url)
    assert form_response.status_code == 200
    form = _page(form_response)
    assert form.select_one('[name=module_id] option[selected]')['value'] == str(first.id)
    supported = [option['value'] for option in form.select('[name=type] option')]
    assert supported == ['card', 'vocabulary', 'matching', 'grammar', 'quiz', 'text', 'final_test']
    body = {'module_id': second.id, 'description': 'Synthetic', 'collection_id': collection.id, 'book_id': book.id}
    for number, kind in enumerate(supported, start=1):
        created = admin_client.post(url, data={**body, 'number': number, 'title': f'Synthetic {kind}', 'type': kind})
        assert created.status_code == 302
        lesson = Lessons.query.filter_by(module_id=second.id, number=number).one()
        assert (lesson.type, lesson.order) == (kind, number)
        assert lesson.collection_id == (collection.id if kind in ('card', 'vocabulary') else None)
        assert lesson.book_id == (book.id if kind == 'text' else None)
        assert created.location == f'/curriculum/admin/lesson/{lesson.id}/edit'
        editor = admin_client.get(created.location)
        assert editor.status_code == 200 and _page(editor).select_one('textarea[name=content]')
    conflict = admin_client.post(url, data={**body, 'number': 1, 'title': 'Conflict', 'type': 'quiz'})
    assert conflict.status_code == 409
    unsupported = admin_client.post(url, data={**body, 'number': 20, 'title': 'Invalid', 'type': 'checkpoint'})
    assert unsupported.status_code == 422
    assert Lessons.query.count() == len(supported)
    lesson = Lessons.query.filter_by(type='grammar').one()
    editor_url = f'/curriculum/admin/lesson/{lesson.id}/edit'
    revision = _page(admin_client.get(editor_url)).select_one('input[name=content_revision]')['value']
    assert admin_client.post(editor_url, data={
        'content_revision': revision, 'content': '{"rule": "Synthetic proof."}',
    }).status_code == 302
    assert lesson.content == {'rule': 'Synthetic proof.'}
    assert AdminAuditLog.query.filter_by(action='curriculum.lesson.create').count() == len(supported)


def test_legacy_curriculum_bookmarks_keep_levels_and_progress_metrics(
    admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    level = CEFRLevel(code='B1', name='Synthetic bookmarked level', order=3)
    module = _module(db_session, level, 1)
    lessons = [Lessons(module_id=module.id, title=f'Synthetic metric {index}', type='quiz', number=index)
               for index in range(1, 4)]
    db_session.add_all(lessons)
    db_session.flush()
    db_session.add_all([LessonProgress(user_id=test_user.id, lesson_id=lesson.id, status=status, score=score)
                        for lesson, status, score in zip(lessons, ['completed', 'completed', 'in_progress'], [72, 0, 99])])
    db_session.commit()
    levels = admin_client.get('/curriculum/admin/levels', follow_redirects=True)
    assert levels.status_code == 200 and levels.request.path == '/admin/curriculum/levels'
    assert level.name in _page(levels).text
    stats = admin_client.get('/curriculum/admin/stats')
    assert stats.status_code == 302 and stats.location == '/admin/curriculum/overview#learning-statistics'
    target = admin_client.get(stats.location)
    assert target.status_code == 200
    page = _page(target).select_one('#learning-statistics')
    assert [dd.get_text(strip=True) for dd in page.select('dd')] == ['2', '72.0']
    assert 'quiz — 3' in page.get_text()
    assert lessons[0].title in page.get_text()


def test_concurrent_lesson_forms_lock_the_module_before_checking_duplicate_number(app: Flask) -> None:
    engine = db.engine
    if engine.dialect.name != 'postgresql':
        pytest.skip('Requires independent PostgreSQL transactions')
    level = CEFRLevel(code='Z9', name='Synthetic concurrency level')
    module = _module(db.session, level, 1)
    administrator = User(username='synthetic_lesson_race', email='lesson-race@example.invalid',
                         active=True, is_admin=True, onboarding_completed=True)
    administrator.set_password('synthetic local test only')
    db.session.add(administrator)
    db.session.commit()
    level_id, module_id, admin_id, login_id = level.id, module.id, administrator.id, administrator.get_id()
    reached_both_locks = Event()
    barrier = Barrier(2, action=reached_both_locks.set)

    def synchronize(
        connection: Connection, cursor: Any, statement: str, parameters: Any,
        context: ExecutionContext, executemany: bool,
    ) -> None:
        if 'FROM modules' in statement and 'FOR UPDATE' in statement:
            barrier.wait(timeout=8)

    def submit() -> int:
        with app.app_context():
            client = app.test_client()
            with client.session_transaction() as session:
                session['_user_id'] = login_id
                session['_fresh'] = True
            return client.post('/admin/curriculum/lessons/create', data={
                'module_id': module_id, 'number': 1, 'title': 'Synthetic concurrency lesson', 'type': 'quiz',
            }).status_code

    event.listen(engine, 'before_cursor_execute', synchronize)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(submit) for _ in range(2)]
            assert sorted(result.result(timeout=12) for result in results) == [302, 409]
        assert reached_both_locks.is_set()
        assert Lessons.query.filter_by(module_id=module_id, number=1).count() == 1
        assert AdminAuditLog.query.filter_by(admin_id=admin_id, action='curriculum.lesson.create').count() == 1
    finally:
        event.remove(engine, 'before_cursor_execute', synchronize)
        db.session.rollback()
        AdminAuditLog.query.filter_by(admin_id=admin_id).delete()
        db.session.delete(db.session.get(CEFRLevel, level_id))
        db.session.delete(db.session.get(User, admin_id))
        db.session.commit()


def test_book_course_analytics_empty_and_scoped_with_real_enrollments(
    admin_client: FlaskClient, test_user: User, db_session: scoped_session,
) -> None:
    path = '/admin/book-courses/analytics'
    empty = admin_client.get(path)
    assert empty.status_code == 200 and 'Книжных курсов пока нет.' in _page(empty).text
    book = Book(title='Synthetic analytical book', author='Synthetic', level='A1', chapters_cnt=0)
    db_session.add(book)
    db_session.flush()
    first = BookCourse(book_id=book.id, title='Synthetic focus course', level='A1', is_active=True)
    second = BookCourse(book_id=book.id, title='Another synthetic course', level='A2', is_active=False)
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add_all([
        BookCourseEnrollment(course_id=first.id, user_id=test_user.id, progress_percentage=75, status='completed'),
        BookCourseEnrollment(course_id=second.id, user_id=test_user.id, progress_percentage=25,
                             enrolled_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=31)),
    ])
    db_session.commit()
    overall = _page(admin_client.get(path))
    assert [dd.get_text(strip=True) for dd in overall.select('dd')] == ['2', '1', '2', '50.0%', '1', '1']
    scoped = _page(admin_client.get(path, query_string={'course_id': first.id}))
    assert [dd.get_text(strip=True) for dd in scoped.select('dd')] == ['1', '1', '1', '75.0%', '1', '1']
    assert first.title in scoped.text and second.title not in scoped.text
    assert len(scoped.select('section[aria-labelledby=enrollments-title] tbody tr')) == 1


def test_audio_statistics_reads_the_flask_connection(
    admin_client: FlaskClient, db_session: scoped_session,
) -> None:
    words = [
        CollectionWords(english_word='synthetic clean', level='A1', get_download=1, listening='pronunciation_en_test.mp3'),
        CollectionWords(english_word='synthetic missing', level='A1', get_download=0, listening=''),
        CollectionWords(english_word='synthetic file', level='A2', get_download=1, listening='[sound:test.mp3]'),
        CollectionWords(english_word='synthetic url', level='A2', get_download=1, listening='https://example.invalid/audio'),
    ]
    db_session.add_all(words)
    db_session.commit()
    stats = AudioManagementService.get_detailed_statistics()
    assert stats == {
        'download_stats': [{'status': 'Available', 'count': 3}, {'status': 'Not Available', 'count': 1}],
        'listening_stats': [{'format_type': name, 'count': 1} for name in ('Anki Format', 'Clean Filename', 'Empty', 'HTTP URL')],
        'level_audio_stats': [{'level': level, 'words_total': 2, 'with_audio': available}
                              for level, available in (('A1', 1), ('A2', 2))],
    }
    page = admin_client.get('/admin/audio/statistics')
    assert page.status_code == 200
    assert 'Статистика аудио файлов' in _page(page).text
    assert all(category in _page(page).text for category in ('A2', 'Clean Filename', 'Available'))
