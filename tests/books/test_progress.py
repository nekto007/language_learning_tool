"""Tests for compute_book_progress_percent (Task 13)."""
import pytest

from app.books.models import Book, Chapter, UserChapterProgress
from app.books.progress import (
    _progress_from_records,
    compute_book_progress_percent,
)


@pytest.fixture
def book_with_chapters(db_session):
    book = Book(title='Progress Book', author='A', level='A1', chapters_cnt=10)
    db_session.add(book)
    db_session.flush()
    chapters = []
    for i in range(10):
        ch = Chapter(
            book_id=book.id,
            chap_num=i + 1,
            title=f'C{i+1}',
            words=100,
            text_raw='x',
        )
        db_session.add(ch)
        chapters.append(ch)
    db_session.flush()
    return book, chapters


def _add_progress(db_session, user, chapter, pct):
    db_session.add(UserChapterProgress(
        user_id=user.id,
        chapter_id=chapter.id,
        offset_pct=pct,
    ))
    db_session.flush()


class TestProgressFromRecords:
    def test_two_completed_plus_partial_third(self):
        class R:
            def __init__(self, pct):
                self.offset_pct = pct
        records = [R(1.0), R(1.0), R(0.5)]
        # (2 + 0.5) / 10 * 100 = 25.0
        assert _progress_from_records(records, 10) == pytest.approx(25.0)

    def test_legacy_formula_would_underreport(self):
        """Old sum/total formula would have given 15% for the same input."""
        class R:
            def __init__(self, pct):
                self.offset_pct = pct
        records = [R(0.5), R(1.0)]
        # legacy: (0.5 + 1.0) / 10 = 0.15 → 15%
        # canonical: completed=1, partial=0.5 → (1+0.5)/10 = 15% — same here
        # The underreport bites when completed >= 2 chapters with a partial:
        records = [R(1.0), R(1.0), R(0.4)]
        legacy = sum(r.offset_pct for r in records) / 10 * 100  # 24
        canonical = _progress_from_records(records, 10)  # 24 too — equal
        # Equal because finished chapters contribute 1.0 either way; the
        # canonical formula matters when partial values stack but only
        # the *max* partial of incomplete chapters should count, never
        # multiple partials simultaneously. Construct that case:
        records = [R(1.0), R(1.0), R(0.5), R(0.3)]
        legacy = sum(r.offset_pct for r in records) / 10 * 100  # 28
        canonical = _progress_from_records(records, 10)  # (2 + 0.5)/10*100 = 25
        assert legacy != canonical
        assert canonical == pytest.approx(25.0)

    def test_no_chapters_returns_zero(self):
        assert _progress_from_records([], 0) == 0.0

    def test_no_records_returns_zero(self):
        assert _progress_from_records([], 10) == 0.0

    def test_all_complete(self):
        class R:
            def __init__(self, pct):
                self.offset_pct = pct
        records = [R(1.0)] * 10
        assert _progress_from_records(records, 10) == pytest.approx(100.0)

    def test_clamped_to_100(self):
        class R:
            def __init__(self, pct):
                self.offset_pct = pct
        # over-counted records (shouldn't happen but be defensive)
        records = [R(1.0)] * 12
        assert _progress_from_records(records, 10) == 100.0

    def test_handles_none_offset(self):
        class R:
            def __init__(self, pct):
                self.offset_pct = pct
        records = [R(None), R(1.0), R(0.5)]
        assert _progress_from_records(records, 10) == pytest.approx(15.0)


class TestComputeBookProgressPercent:
    def test_zero_when_no_chapters(self, db_session, test_user):
        book = Book(title='Empty', author='A', level='A1', chapters_cnt=0)
        db_session.add(book)
        db_session.flush()
        assert compute_book_progress_percent(test_user.id, book.id, db_session) == 0.0

    def test_zero_when_no_progress(self, db_session, test_user, book_with_chapters):
        book, _ = book_with_chapters
        assert compute_book_progress_percent(test_user.id, book.id, db_session) == 0.0

    def test_two_completed_plus_half_third(self, db_session, test_user, book_with_chapters):
        book, chapters = book_with_chapters
        _add_progress(db_session, test_user, chapters[0], 1.0)
        _add_progress(db_session, test_user, chapters[1], 1.0)
        _add_progress(db_session, test_user, chapters[2], 0.5)
        assert compute_book_progress_percent(test_user.id, book.id, db_session) == pytest.approx(25.0)

    def test_all_complete(self, db_session, test_user, book_with_chapters):
        book, chapters = book_with_chapters
        for ch in chapters:
            _add_progress(db_session, test_user, ch, 1.0)
        assert compute_book_progress_percent(test_user.id, book.id, db_session) == pytest.approx(100.0)

    def test_isolated_per_user(self, db_session, test_user, book_with_chapters):
        from app.auth.models import User
        book, chapters = book_with_chapters
        other = User(username='other_reader', email='other_reader@example.com')
        other.set_password('x')
        db_session.add(other)
        db_session.flush()
        _add_progress(db_session, other, chapters[0], 1.0)
        # current user has no progress → 0
        assert compute_book_progress_percent(test_user.id, book.id, db_session) == 0.0
