"""Tests for admin book management: sync_book_course_from_book, cascade delete,
slug uniqueness, and chapter audio field behaviour (Task 44)."""
import uuid

import pytest

from app.books.models import Book, Chapter
from app.curriculum.book_courses import BookCourse, generate_slug, sync_book_course_from_book
from app.utils.db import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_book(db_session, title="Test Book", author="Author", level="B1"):
    book = Book(
        title=title,
        author=author,
        chapters_cnt=0,
        level=level,
    )
    db_session.add(book)
    db_session.flush()
    return book


def _make_book_course(db_session, book, title=None, description=None, slug=None):
    course = BookCourse(
        book_id=book.id,
        title=title or f"Course for {book.title}",
        description=description or "Original description",
        level=book.level or "B1",
        slug=slug,
    )
    db_session.add(course)
    db_session.flush()
    return course


# ---------------------------------------------------------------------------
# 1. sync_book_course_from_book — does NOT overwrite title/description
# ---------------------------------------------------------------------------


class TestSyncBookCourseFields:
    """sync_book_course_from_book must not overwrite curated title/description."""

    @pytest.mark.smoke
    def test_sync_does_not_overwrite_title(self, app, db_session):
        book = _make_book(db_session, title="Original Book Title")
        course = _make_book_course(db_session, book, title="Curated Course Title")
        original_title = course.title

        sync_book_course_from_book(book.id, db_session)
        db_session.flush()

        db_session.refresh(course)
        assert course.title == original_title, (
            "sync_book_course_from_book must not overwrite course.title"
        )

    def test_sync_does_not_overwrite_description(self, app, db_session):
        book = _make_book(db_session, title="Book With Description")
        course = _make_book_course(
            db_session, book, description="Curated description text"
        )
        original_desc = course.description

        sync_book_course_from_book(book.id, db_session)
        db_session.flush()

        db_session.refresh(course)
        assert course.description == original_desc, (
            "sync_book_course_from_book must not overwrite course.description"
        )

    def test_sync_updates_slug_from_book_title(self, app, db_session):
        book = _make_book(db_session, title="My Amazing Book")
        course = _make_book_course(db_session, book, slug="old-slug")

        sync_book_course_from_book(book.id, db_session)
        db_session.flush()

        db_session.refresh(course)
        assert course.slug == "my-amazing-book"

    def test_sync_updates_level_from_book(self, app, db_session):
        book = _make_book(db_session, title="Level Book", level="C1")
        course = _make_book_course(db_session, book)
        course.level = "A1"  # Stale value
        db_session.flush()

        sync_book_course_from_book(book.id, db_session)
        db_session.flush()

        db_session.refresh(course)
        assert course.level == "C1"

    def test_sync_returns_zero_for_nonexistent_book(self, app, db_session):
        result = sync_book_course_from_book(999999, db_session)
        assert result == 0

    def test_sync_returns_zero_when_no_courses(self, app, db_session):
        book = _make_book(db_session, title="Solo Book")
        result = sync_book_course_from_book(book.id, db_session)
        assert result == 0


# ---------------------------------------------------------------------------
# 2. Book delete cascades to BookCourse
# ---------------------------------------------------------------------------


class TestBookDeleteCascade:
    """Deleting a Book must cascade-delete associated BookCourse rows."""

    @pytest.mark.smoke
    def test_delete_book_removes_book_course(self, app, db_session):
        book = _make_book(db_session, title="Book To Delete")
        course = _make_book_course(db_session, book)
        course_id = course.id
        db_session.flush()

        # Simulate what the admin route does: delete book via ORM.
        db_session.delete(book)
        db_session.flush()

        # Expire identity map so the next get() hits the DB instead of cache.
        db_session.expire_all()

        # BookCourse must be gone (DB-level ON DELETE CASCADE).
        found = db_session.get(BookCourse, course_id)
        assert found is None, (
            "BookCourse must be deleted when parent Book is deleted"
        )

    def test_delete_book_removes_chapters(self, app, db_session):
        book = _make_book(db_session, title="Book With Chapters")
        chapter = Chapter(
            book_id=book.id,
            chap_num=1,
            title="Chapter 1",
            words=100,
            text_raw="Some text",
        )
        db_session.add(chapter)
        db_session.flush()
        chapter_id = chapter.id

        db_session.delete(book)
        db_session.flush()

        assert db_session.get(Chapter, chapter_id) is None

    def test_delete_book_with_no_courses_succeeds(self, app, db_session):
        book = _make_book(db_session, title="Lonely Book")
        book_id = book.id
        db_session.flush()

        db_session.delete(book)
        db_session.flush()

        assert db_session.get(Book, book_id) is None


# ---------------------------------------------------------------------------
# 3. Book slug unique constraint — friendly handling
# ---------------------------------------------------------------------------


class TestSlugUniqueness:
    """When two books share the same title, sync must not raise IntegrityError."""

    @pytest.mark.smoke
    def test_slug_collision_resolved_with_suffix(self, app, db_session):
        book1 = _make_book(db_session, title="Shared Title")
        book2 = _make_book(db_session, title="Shared Title")
        course1 = _make_book_course(db_session, book1, slug="shared-title")
        course2 = _make_book_course(db_session, book2, slug="different-slug")
        db_session.flush()

        # sync book2 — its generated slug "shared-title" clashes with course1
        sync_book_course_from_book(book2.id, db_session)
        db_session.flush()  # Must not raise IntegrityError

        db_session.refresh(course2)
        # course2 must NOT have the same slug as course1
        assert course2.slug != "shared-title", (
            "Slug collision must be resolved; conflicting course must get a unique slug"
        )
        # The suffix form uses course.id
        assert course2.slug == f"shared-title-{course2.id}"

    def test_slug_no_collision_uses_plain_slug(self, app, db_session):
        book = _make_book(db_session, title=f"Unique Title {uuid.uuid4().hex[:6]}")
        course = _make_book_course(db_session, book, slug="old-slug")
        db_session.flush()

        sync_book_course_from_book(book.id, db_session)
        db_session.flush()

        db_session.refresh(course)
        # No collision — plain generated slug must be used (no suffix)
        expected_slug = generate_slug(book.title)
        assert course.slug == expected_slug, (
            f"Expected plain slug {expected_slug!r}, got {course.slug!r}"
        )


# ---------------------------------------------------------------------------
# 4. Chapter audio — no admin upload endpoint; audio_url is a URL field
# ---------------------------------------------------------------------------


class TestChapterAudioField:
    """Chapter.audio_url is a URL field, not an admin upload endpoint.
    There is no MIME-check needed on the server for this field because the
    admin sets it as a text URL (e.g. an S3 URL), not a file upload.
    These tests document and assert that invariant."""

    def test_chapter_audio_url_accepts_string(self, app, db_session):
        book = _make_book(db_session, title="Audio Book")
        chapter = Chapter(
            book_id=book.id,
            chap_num=1,
            title="Ch1",
            words=50,
            text_raw="text",
            audio_url="https://s3.example.com/audio/ch1.mp3",
        )
        db_session.add(chapter)
        db_session.flush()

        db_session.refresh(chapter)
        assert chapter.audio_url == "https://s3.example.com/audio/ch1.mp3"

    def test_chapter_audio_url_nullable(self, app, db_session):
        book = _make_book(db_session, title="Silent Book")
        chapter = Chapter(
            book_id=book.id,
            chap_num=1,
            title="Ch1",
            words=50,
            text_raw="text",
            audio_url=None,
        )
        db_session.add(chapter)
        db_session.flush()

        db_session.refresh(chapter)
        assert chapter.audio_url is None

    def test_no_admin_chapter_audio_upload_endpoint(self, app):
        """Verify no /admin/books/*/chapter/*/upload-audio route exists.
        Chapter audio is managed via URL field, not file upload."""
        rules = [str(rule) for rule in app.url_map.iter_rules()]
        audio_upload_routes = [
            r for r in rules
            if "chapter" in r and "audio" in r and "upload" in r
        ]
        assert audio_upload_routes == [], (
            "No admin chapter audio upload endpoint should exist; "
            "audio_url is a plain URL field"
        )
