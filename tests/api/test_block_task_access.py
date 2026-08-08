"""Regression tests for SEC-001 (cross-zone audit 2026-08-08).

``GET /api/tasks/<id>``, ``GET /api/blocks/<id>`` and ``GET /api/blocks/<id>/tasks``
used to serve derived course material for ``companion_only`` books to any
authenticated user, bypassing ``can_user_access_book``. Their neighbours in the
same blueprint call both gates; these three did not.
"""
from __future__ import annotations

import pytest

from app.books.models import Block, Book, Task, TaskType
from app.modules.models import SystemModule, UserModule


@pytest.fixture
def _books_module(db_session):
    mod = SystemModule.query.filter_by(code='books').first()
    if mod is None:
        mod = SystemModule(
            code='books', name='Книги', description='', icon='book-open',
            is_active=True, is_default=False, order=10,
        )
        db_session.add(mod)
        db_session.flush()
    return mod


def _grant_books(db_session, user, module):
    existing = UserModule.query.filter_by(user_id=user.id, module_id=module.id).first()
    if existing:
        existing.is_enabled = True
    else:
        db_session.add(UserModule(
            user_id=user.id, module_id=module.id,
            is_enabled=True, granted_by_admin=True,
        ))
    db_session.flush()


def _make_material(db_session, *, rights_status: str, is_published: bool = True):
    book = Book(
        title='Companion Book', author='A', level='A1', chapters_cnt=1,
        rights_status=rights_status, is_published=is_published,
    )
    db_session.add(book)
    db_session.flush()

    block = Block(book_id=book.id, block_num=1, grammar_key='present_perfect')
    db_session.add(block)
    db_session.flush()

    task = Task(
        block_id=block.id,
        task_type=TaskType.reading_mcq,
        payload={'questions': [{'q': 'secret', 'answer': 'secret'}]},
    )
    db_session.add(task)
    db_session.flush()
    return book, block, task


class TestCompanionOnlyIsGated:
    """A user without the ``books`` module must not read companion material."""

    def test_task_payload_is_forbidden(self, authenticated_client, db_session):
        _, _, task = _make_material(db_session, rights_status='companion_only')

        response = authenticated_client.get(f'/api/tasks/{task.id}')

        assert response.status_code == 403
        assert 'secret' not in response.get_data(as_text=True)

    def test_block_detail_is_forbidden(self, authenticated_client, db_session):
        _, block, _ = _make_material(db_session, rights_status='companion_only')

        response = authenticated_client.get(f'/api/blocks/{block.id}')

        assert response.status_code == 403
        assert 'present_perfect' not in response.get_data(as_text=True)

    def test_block_task_list_is_forbidden(self, authenticated_client, db_session):
        _, block, _ = _make_material(db_session, rights_status='companion_only')

        response = authenticated_client.get(f'/api/blocks/{block.id}/tasks')

        assert response.status_code == 403


class TestAccessIsRestoredWithTheModule:
    def test_task_readable_with_books_module(
        self, authenticated_client, db_session, test_user, _books_module,
    ):
        _, _, task = _make_material(db_session, rights_status='companion_only')
        _grant_books(db_session, test_user, _books_module)

        response = authenticated_client.get(f'/api/tasks/{task.id}')

        assert response.status_code == 200
        assert response.get_json()['task']['payload']['questions'][0]['q'] == 'secret'

    def test_public_domain_readable_without_module(self, authenticated_client, db_session):
        _, block, task = _make_material(db_session, rights_status='public_domain')

        assert authenticated_client.get(f'/api/tasks/{task.id}').status_code == 200
        assert authenticated_client.get(f'/api/blocks/{block.id}').status_code == 200
        assert authenticated_client.get(f'/api/blocks/{block.id}/tasks').status_code == 200


class TestDraftBooksLookNonexistent:
    def test_draft_public_domain_block_is_404_not_403(self, authenticated_client, db_session):
        _, block, task = _make_material(
            db_session, rights_status='public_domain', is_published=False,
        )

        assert authenticated_client.get(f'/api/blocks/{block.id}').status_code == 404
        assert authenticated_client.get(f'/api/tasks/{task.id}').status_code == 404


def _make_daily_lesson_task(db_session, *, rights_status: str, is_published: bool = True):
    """A task that reaches its book through ``daily_lesson.chapter``, not a block.

    ``Task.block_id`` is nullable by design, so this is the arm ``_task_gate``
    exists for — gating it on ``task.block`` alone 404'd every daily lesson.
    """
    from app.books.models import Chapter
    from app.curriculum.book_courses import BookCourse, BookCourseModule
    from app.curriculum.daily_lessons import DailyLesson

    book = Book(
        title='Course Book', author='A', level='A1', chapters_cnt=1,
        rights_status=rights_status, is_published=is_published,
    )
    db_session.add(book)
    db_session.flush()

    chapter = Chapter(book_id=book.id, chap_num=1, title='Ch 1', text_raw='text', words=1)
    db_session.add(chapter)
    course = BookCourse(book_id=book.id, title='Course', level='A1')
    db_session.add(course)
    db_session.flush()

    module = BookCourseModule(course_id=course.id, module_number=1, title='M1')
    db_session.add(module)
    task = Task(
        block_id=None,
        task_type=TaskType.vocabulary,
        payload={'phrases': ['classified']},
    )
    db_session.add_all([module, task])
    db_session.flush()

    db_session.add(DailyLesson(
        book_course_module_id=module.id, slice_number=1, day_number=1,
        chapter_id=chapter.id, lesson_type='vocabulary', task_id=task.id,
    ))
    db_session.flush()
    return book, task


class TestDailyLessonTaskUsesTheSameGate:
    def test_companion_only_daily_lesson_task_is_forbidden(
        self, authenticated_client, db_session,
    ):
        _, task = _make_daily_lesson_task(db_session, rights_status='companion_only')

        response = authenticated_client.get(f'/api/tasks/{task.id}')

        assert response.status_code == 403
        assert 'classified' not in response.get_data(as_text=True)

    def test_public_domain_daily_lesson_task_is_readable(
        self, authenticated_client, db_session,
    ):
        _, task = _make_daily_lesson_task(db_session, rights_status='public_domain')

        response = authenticated_client.get(f'/api/tasks/{task.id}')

        assert response.status_code == 200
        assert response.get_json()['task']['payload']['phrases'] == ['classified']

    def test_draft_daily_lesson_task_is_404(self, authenticated_client, db_session):
        _, task = _make_daily_lesson_task(
            db_session, rights_status='public_domain', is_published=False,
        )

        assert authenticated_client.get(f'/api/tasks/{task.id}').status_code == 404


class TestBookContentIsGated:
    """``/api/book/<id>/content`` resolved a Book without going through the gate."""

    def test_companion_only_content_is_forbidden(self, authenticated_client, db_session):
        book, _, _ = _make_material(db_session, rights_status='companion_only')

        response = authenticated_client.get(f'/api/book/{book.id}/content')

        assert response.status_code == 403
        assert 'Companion Book' not in response.get_data(as_text=True)

    def test_draft_content_is_404_not_500(self, authenticated_client, db_session):
        book, _, _ = _make_material(
            db_session, rights_status='public_domain', is_published=False,
        )

        assert authenticated_client.get(f'/api/book/{book.id}/content').status_code == 404

    def test_missing_book_is_404_not_500(self, authenticated_client):
        assert authenticated_client.get('/api/book/99999999/content').status_code == 404

    def test_public_domain_content_is_readable(self, authenticated_client, db_session):
        book, _, _ = _make_material(db_session, rights_status='public_domain')

        response = authenticated_client.get(f'/api/book/{book.id}/content')

        assert response.status_code == 200
        assert response.get_json()['content']['title'] == 'Companion Book'


class TestOrphanTaskFailsClosed:
    def test_task_without_block_is_not_found(self, authenticated_client, db_session):
        task = Task(
            block_id=None,
            task_type=TaskType.vocabulary,
            payload={'phrases': ['orphan']},
        )
        db_session.add(task)
        db_session.flush()

        response = authenticated_client.get(f'/api/tasks/{task.id}')

        assert response.status_code == 404
        assert 'orphan' not in response.get_data(as_text=True)
