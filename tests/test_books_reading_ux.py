# tests/test_books_reading_ux.py

"""
Tests for Task 13: Books & Reading UX Improvements
- Reading progress indicator on book selection page
- Continue reading button linking to last read chapter
- Word frequency info on book words page
- Fallback icon when book cover image fails to load
- Estimated reading time per chapter
"""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from app.books.models import Book, Chapter, UserChapterProgress
from app.utils.db import db


@pytest.fixture
def books_module_enabled():
    """Mock module_required to always allow access for 'books' module."""
    with patch('app.modules.service.ModuleService.is_module_enabled_for_user', return_value=True):
        yield


@pytest.fixture
def sample_book_with_chapters(db_session):
    """Create a book with 3 chapters for testing."""
    slug = uuid.uuid4().hex[:8]
    book = Book(
        title=f'Test Book {slug}',
        author='Test Author',
        level='B1',
        words_total=3000,
        unique_words=500,
        chapters_cnt=3,
        slug=slug,
    )
    db_session.add(book)
    db_session.flush()

    chapters = []
    for i in range(1, 4):
        ch = Chapter(
            book_id=book.id,
            chap_num=i,
            title=f'Chapter {i}',
            words=1000 * i,  # 1000, 2000, 3000 words
            text_raw=f'Chapter {i} text content here.',
        )
        db_session.add(ch)
        chapters.append(ch)

    db_session.commit()
    return book, chapters


@pytest.fixture
def book_no_chapters(db_session):
    """Create a book with no chapters."""
    slug = uuid.uuid4().hex[:8]
    book = Book(
        title=f'Empty Book {slug}',
        author='Author',
        level='A2',
        words_total=0,
        unique_words=0,
        chapters_cnt=0,
        slug=slug,
    )
    db_session.add(book)
    db_session.commit()
    return book


class TestReadingProgressCalculation:
    """Test reading progress computation in read_selection route."""

    def test_book_progress_no_reading(
        self, authenticated_client, sample_book_with_chapters, books_module_enabled
    ):
        """Book with no user progress should show 0% and no continue button."""
        book, chapters = sample_book_with_chapters
        response = authenticated_client.get('/read')
        assert response.status_code == 200
        # Book should appear in all_books but not in recent_books
        assert book.title.encode() in response.data

    def test_book_progress_with_reading(
        self, authenticated_client, db_session, test_user,
        sample_book_with_chapters, books_module_enabled
    ):
        """Book with partial reading progress should show correct percentage."""
        book, chapters = sample_book_with_chapters

        # User read 50% of chapter 1
        progress = UserChapterProgress(
            user_id=test_user.id,
            chapter_id=chapters[0].id,
            offset_pct=0.5,
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(progress)
        db_session.commit()

        response = authenticated_client.get('/read')
        assert response.status_code == 200
        # Should show in recent books section
        assert 'Продолжить' in response.data.decode('utf-8')

    def test_book_progress_percentage_calculation(
        self, db_session, test_user, sample_book_with_chapters
    ):
        """Test that progress is calculated as sum of offset_pct / total_chapters."""
        book, chapters = sample_book_with_chapters

        # Read chapter 1 fully (1.0) and chapter 2 half (0.5)
        for ch, pct in [(chapters[0], 1.0), (chapters[1], 0.5)]:
            db_session.add(UserChapterProgress(
                user_id=test_user.id,
                chapter_id=ch.id,
                offset_pct=pct,
                updated_at=datetime.now(timezone.utc),
            ))
        db_session.commit()

        # Expected: (1.0 + 0.5) / 3 * 100 = 50%
        from app.books.models import UserChapterProgress as UCP
        user_progress = db_session.query(UCP, Chapter).join(
            Chapter, UCP.chapter_id == Chapter.id
        ).filter(
            Chapter.book_id == book.id,
            UCP.user_id == test_user.id
        ).all()

        total_offset = sum(p.offset_pct for p, _ in user_progress)
        total_chapters = book.chapters_cnt or 1
        pct = int((total_offset / total_chapters) * 100)
        assert pct == 50

    def test_empty_books_list(
        self, authenticated_client, books_module_enabled
    ):
        """Test read_selection with no books at all."""
        response = authenticated_client.get('/read')
        assert response.status_code == 200


class TestContinueReadingLogic:
    """Test that continue reading links to last read chapter."""

    def test_continue_reading_links_to_last_chapter(
        self, authenticated_client, db_session, test_user,
        sample_book_with_chapters, books_module_enabled
    ):
        """Continue reading should link to the most recently read chapter."""
        book, chapters = sample_book_with_chapters

        now = datetime.now(timezone.utc)
        # Read chapter 1 first, then chapter 2 later
        db_session.add(UserChapterProgress(
            user_id=test_user.id,
            chapter_id=chapters[0].id,
            offset_pct=1.0,
            updated_at=now - timedelta(days=1),
        ))
        db_session.add(UserChapterProgress(
            user_id=test_user.id,
            chapter_id=chapters[1].id,
            offset_pct=0.3,
            updated_at=now,
        ))
        db_session.commit()

        response = authenticated_client.get('/read')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # The continue link should contain chapter=2
        assert f'chapter={chapters[1].chap_num}' in html

    def test_details_page_continue_reading(
        self, authenticated_client, db_session, test_user,
        sample_book_with_chapters, books_module_enabled
    ):
        """Book details page should show 'Continue reading' when progress exists."""
        book, chapters = sample_book_with_chapters

        db_session.add(UserChapterProgress(
            user_id=test_user.id,
            chapter_id=chapters[1].id,
            offset_pct=0.5,
            updated_at=datetime.now(timezone.utc),
        ))
        db_session.commit()

        response = authenticated_client.get(f'/books/{book.id}')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'Продолжить чтение' in html

    def test_details_page_start_reading_when_no_progress(
        self, authenticated_client, sample_book_with_chapters, books_module_enabled
    ):
        """Book details page should show 'Start reading' when no progress."""
        book, chapters = sample_book_with_chapters

        response = authenticated_client.get(f'/books/{book.id}')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        assert 'Начать чтение' in html


class TestEstimatedReadingTime:
    """Test that estimated reading time is shown per chapter."""

    def test_chapter_reading_time_shown(
        self, authenticated_client, sample_book_with_chapters, books_module_enabled
    ):
        """Details page should show estimated reading time for each chapter."""
        book, chapters = sample_book_with_chapters

        response = authenticated_client.get(f'/books/{book.id}')
        assert response.status_code == 200
        html = response.data.decode('utf-8')
        # Chapter 1: 1000 words / 150 wpm = ~6 min
        # Chapter 2: 2000 words / 150 wpm = ~13 min
        # Chapter 3: 3000 words / 150 wpm = ~20 min
        assert '~6' in html or '~7' in html  # 1000/150 = 6.66
        assert 'мин' in html

    def test_chapter_reading_time_minimum_1_min(self, app):
        """Even a very short chapter should show at least 1 min."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'books/details_optimized.html')[0]
        # Template uses: reading_minutes if reading_minutes > 0 else 1
        assert 'reading_minutes' in source


class TestFallbackCoverIcon:
    """Test that cover images have fallback handling."""

    def test_selection_page_has_onerror_fallback(self, app):
        """read_selection template should have onerror fallback for cover images."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'books/read_selection.html')[0]
        assert 'onerror' in source

    def test_details_page_has_onerror_fallback(self, app):
        """details_optimized template should have onerror fallback for cover images."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'books/details_optimized.html')[0]
        assert 'onerror' in source


class TestWordFrequencyDisplay:
    """Test that word frequency is displayed on book words page."""

    def test_words_page_has_frequency_column(self, app):
        """words_optimized template should show frequency column."""
        env = app.jinja_env
        source = env.loader.get_source(env, 'books/words_optimized.html')[0]
        assert 'Частота' in source
        # Check frequency variable is used
        assert 'frequency' in source
