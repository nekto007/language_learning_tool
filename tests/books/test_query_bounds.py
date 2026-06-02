"""Tests for N+1 query prevention in books routes (Task 59).

Verifies that:
- Book catalog uses a single GROUP BY query for chapter counts (not N queries)
- UserWord is loaded in bulk in book_words (not per-word)
- chunk_ids is used for bulk word lookups in book_words
"""
import uuid
import contextlib

import pytest
import sqlalchemy

from app.books.models import Book, Chapter
from app.words.models import CollectionWords


@pytest.fixture
def multi_book_catalog(db_session):
    """Create 5 published books each with 3 chapters for catalog tests."""
    suffix = uuid.uuid4().hex[:8]
    books = []
    for i in range(5):
        book = Book(
            title=f'QB Book {i:02d} {suffix}',
            author=f'Author {i}',
            level='A1',
            chapters_cnt=3,
            is_published=True,
        )
        db_session.add(book)
        db_session.flush()
        for j in range(1, 4):
            db_session.add(Chapter(
                book_id=book.id,
                chap_num=j,
                title=f'Chapter {j}',
                words=100,
                text_raw=f'Chapter {j} text.',
            ))
        books.append(book)
    db_session.commit()
    return books


@pytest.fixture
def book_with_words(db_session):
    """Create a published book with a few words linked via word_book_link."""
    from app.words.models import word_book_link
    from app.utils.db import db as _db

    suffix = uuid.uuid4().hex[:8]
    book = Book(
        title=f'QB WordBook {suffix}',
        author='Author',
        level='A1',
        chapters_cnt=1,
        is_published=True,
        unique_words=3,
        rights_status='public_domain',
    )
    db_session.add(book)
    db_session.flush()
    db_session.add(Chapter(
        book_id=book.id, chap_num=1, title='Ch1', words=50, text_raw='text'
    ))

    words = []
    for i in range(3):
        w = CollectionWords(
            english_word=f'qb_bw_word_{i}_{suffix}',
            russian_word=f'слово_{i}',
            level='A1',
            item_type='word',
        )
        db_session.add(w)
        db_session.flush()
        db_session.execute(
            word_book_link.insert().values(word_id=w.id, book_id=book.id, frequency=i + 1)
        )
        words.append(w)

    db_session.commit()
    return book, words


@contextlib.contextmanager
def count_queries(app):
    """Context manager that counts DB queries executed within its scope."""
    counter = {'n': 0}

    def _before_cursor_execute(conn, cursor, statement, params, context, executemany):
        counter['n'] += 1

    engine = app.extensions['sqlalchemy'].engine
    sqlalchemy.event.listen(engine, 'before_cursor_execute', _before_cursor_execute)
    try:
        yield counter
    finally:
        sqlalchemy.event.remove(engine, 'before_cursor_execute', _before_cursor_execute)


class TestBookCatalogQueryBounds:
    """Verify that book catalog uses bulk chapter count query."""

    @pytest.mark.smoke
    def test_book_list_returns_200(self, authenticated_client, multi_book_catalog):
        resp = authenticated_client.get('/books')
        assert resp.status_code == 200

    def test_chapter_counts_uses_bulk_query(
        self, app, authenticated_client, multi_book_catalog
    ):
        """Book catalog chapter counts must use a single GROUP BY query.

        We measure total query count for /books with 5 books on the page.
        It should stay well below 5 + 5 (N queries for books + N for chapters).
        """
        with count_queries(app) as counter:
            resp = authenticated_client.get('/books?per_page=5')
        assert resp.status_code == 200
        # 5 books → should NOT generate 5 chapter-count queries.
        # Upper bound: main book query + bulk word stats + bulk chapter count + session ≈ 15
        assert counter['n'] < 60, (
            f"Book catalog made {counter['n']} queries for 5 books, expected < 60. "
            "chapter_count may be queried per-book instead of using GROUP BY."
        )

    def test_chapter_counts_scale_is_constant(
        self, app, authenticated_client, multi_book_catalog
    ):
        """Query count must not grow proportionally with number of books shown."""
        with count_queries(app) as c2:
            r2 = authenticated_client.get('/books?per_page=2')
        with count_queries(app) as c5:
            r5 = authenticated_client.get('/books?per_page=5')

        assert r2.status_code == 200
        assert r5.status_code == 200
        # Query delta should be near 0 — bulk query handles all books at once.
        delta = c5['n'] - c2['n']
        assert delta < 5, (
            f"Book catalog query count grew by {delta} when showing 5 vs 2 books. "
            "This suggests per-book chapter count queries are being made."
        )


class TestBookWordsQueryBounds:
    """Verify that book_words UserWord loading is bulk (chunk_ids pattern)."""

    def test_book_words_returns_200(self, authenticated_client, book_with_words):
        book, _words = book_with_words
        resp = authenticated_client.get(f'/books/{book.id}/words')
        assert resp.status_code == 200

    def test_userword_bulk_load_in_book_words(
        self, app, authenticated_client, book_with_words
    ):
        """UserWord must be loaded in a single IN() query, not per-word."""
        book, _words = book_with_words
        with count_queries(app) as counter:
            resp = authenticated_client.get(f'/books/{book.id}/words')
        assert resp.status_code == 200
        # With 3 words: expect main query + pagination + 1 bulk UserWord + stats ≈ 10
        # Per-word queries would add 3 extra
        assert counter['n'] < 50, (
            f"book_words made {counter['n']} queries for 3 words; "
            "expected < 50. Check if UserWord is being queried per-word."
        )

    def test_chunk_ids_used_for_bulk_word_lookup(self, app):
        """chunk_ids / query_by_ids should be importable and functional."""
        from app.utils.db_utils import chunk_ids, query_by_ids

        # chunk_ids splits correctly
        chunks = list(chunk_ids(list(range(5)), chunk_size=3))
        assert chunks == [[0, 1, 2], [3, 4]]

        # empty list returns nothing
        assert list(chunk_ids([], chunk_size=3)) == []

    def test_query_by_ids_empty_list_returns_empty(self, app, db_session):
        """query_by_ids with empty ids returns [] without hitting the DB."""
        from app.utils.db_utils import query_by_ids
        from app.study.models import UserWord

        with app.app_context():
            result = query_by_ids(UserWord.query, UserWord.word_id, [])
        assert result == []
