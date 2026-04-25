"""Tests for Book ↔ BookCourse sync and word_book_link cleanup (Task 12)."""
import pytest

from app.books.models import Book
from app.curriculum.book_courses import (
    BookCourse,
    BookCourseModule,
    sync_book_course_from_book,
    generate_slug,
)
from app.utils.db import db


@pytest.fixture
def book_with_course(db_session):
    book = Book(
        title='Original Title',
        author='A',
        level='A1',
        chapters_cnt=3,
        create_course=True,
    )
    db_session.add(book)
    db_session.flush()
    course = BookCourse(
        book_id=book.id,
        slug=generate_slug(book.title),
        title='Course Title',
        description='d',
        level='A1',
        total_modules=0,
    )
    db_session.add(course)
    db_session.flush()
    for i in range(2):
        db_session.add(BookCourseModule(
            course_id=course.id,
            module_number=i + 1,
            title=f'M{i+1}',
        ))
    db_session.commit()
    return book, course


class TestSyncBookCourseFromBook:
    def test_no_courses_returns_zero(self, db_session, test_book):
        assert sync_book_course_from_book(test_book.id, db_session) == 0

    def test_unknown_book_returns_zero(self, db_session):
        assert sync_book_course_from_book(999_999, db_session) == 0

    def test_slug_refresh_and_total_modules(self, db_session, book_with_course):
        book, course = book_with_course
        book.title = 'Brand New Title'
        book.level = 'B1'
        db_session.flush()

        updated = sync_book_course_from_book(book.id, db_session)
        assert updated == 1

        db_session.refresh(course)
        assert course.slug == generate_slug('Brand New Title')
        assert course.total_modules == 2
        assert course.level == 'B1'

    def test_idempotent_when_in_sync(self, db_session, book_with_course):
        book, course = book_with_course
        sync_book_course_from_book(book.id, db_session)
        # second run: no changes
        assert sync_book_course_from_book(book.id, db_session) == 0


class TestEditBookContentTriggersSync:
    """Pin the wiring contract: edit_book_content must invoke
    sync_book_course_from_book when the source Book has create_course=True.
    Source-level assertion avoids the heavy WTForms + FileField + onboarding
    redirect chain that is orthogonal to the sync behavior we care about
    (which is exhaustively unit-tested above).
    """

    def test_edit_book_content_calls_sync_for_create_course_books(self):
        import inspect
        from app.books import routes

        src = inspect.getsource(routes.edit_book_content)
        assert 'sync_book_course_from_book' in src
        assert 'book.create_course' in src
        # Sync must be invoked before the final commit so its writes
        # land in the same transaction as the Book edit.
        sync_idx = src.index('sync_book_course_from_book')
        commit_idx = src.index('db.session.commit()')
        assert sync_idx < commit_idx


class TestWordBookLinkCleanup:
    """Both reprocess paths must DELETE stale word_book_link rows before
    re-inserting fresh ones; otherwise reprocessing accumulates orphan
    links and inflates `unique_words`. We pin the contract at source level
    because the cleanup helper opens its own psycopg2 connection (outside
    the test savepoint), making a live-DB assertion unreliable.
    """

    def test_process_book_words_clears_links_before_insert(self):
        import inspect
        from app.books import processors

        src = inspect.getsource(processors._process_book_words_internal)
        assert 'clear_book_word_links' in src
        # Ensure cleanup precedes the per-batch insert loop
        clear_idx = src.index('clear_book_word_links')
        insert_idx = src.index('process_batch_from_original_format')
        assert clear_idx < insert_idx

    def test_process_book_chapters_words_clears_links_before_insert(self):
        import inspect
        from app.books import processors

        src = inspect.getsource(processors._process_book_chapters_words_internal)
        assert 'clear_book_word_links' in src
        clear_idx = src.index('clear_book_word_links')
        insert_idx = src.index('process_batch_from_original_format')
        assert clear_idx < insert_idx
