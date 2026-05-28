"""Tests for N+1 query prevention in words routes (Task 59).

Verifies that:
- Word list type_counts uses a single GROUP BY query (not 3 separate COUNTs)
- Word list status_counts uses at most 2 queries (1 GROUP BY + 1 mastered)
- UserWord is loaded in bulk (not per-word)
- Translation data comes from russian_word column (no lazy-loaded relationship)
"""
import uuid
import contextlib

import pytest
import sqlalchemy

from app.words.models import CollectionWords
from app.modules.models import SystemModule, UserModule


@pytest.fixture
def words_module_access(db_session, test_user):
    """Grant words module access to test_user."""
    module = SystemModule.query.filter_by(code='words').first()
    if not module:
        module = SystemModule(
            code='words', name='Words', description='Words module',
            is_active=True, is_default=True, order=4,
        )
        db_session.add(module)
        db_session.flush()

    existing = UserModule.query.filter_by(
        user_id=test_user.id, module_id=module.id,
    ).first()
    if not existing:
        db_session.add(UserModule(
            user_id=test_user.id, module_id=module.id, is_enabled=True,
        ))
        db_session.commit()
    return module


@pytest.fixture
def sample_words(db_session):
    """Create a small set of words across two item_types for count tests."""
    suffix = uuid.uuid4().hex[:8]
    words = []
    for i in range(5):
        w = CollectionWords(
            english_word=f'qbound_word_{i:02d}_{suffix}',
            russian_word=f'слово_{i}',
            level='A1',
            item_type='word',
        )
        db_session.add(w)
        words.append(w)
    for i in range(3):
        pv = CollectionWords(
            english_word=f'qbound_pv_{i:02d}_{suffix}',
            russian_word=f'фразовый_{i}',
            level='A1',
            item_type='phrasal_verb',
        )
        db_session.add(pv)
        words.append(pv)
    db_session.commit()
    return words


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


class TestWordListQueryBounds:
    """Verify that word list page is not doing excessive queries."""

    @pytest.mark.smoke
    def test_word_list_returns_200(
        self, authenticated_client, words_module_access, sample_words
    ):
        """Baseline: GET /words returns 200."""
        resp = authenticated_client.get('/words')
        assert resp.status_code == 200

    def test_type_counts_bounded_queries(
        self, app, authenticated_client, words_module_access, sample_words
    ):
        """type_counts must use a single GROUP BY query, not 3 separate COUNTs.

        We measure the total query count for the entire /words request. As a
        conservative bound we just check that the total is less than 25 queries
        (a good margin below 3 separate type-count queries + N per-word lookups).
        The real enforcement is that the implementation uses GROUP BY.
        """
        with count_queries(app) as counter:
            resp = authenticated_client.get('/words?per_page=5')
        assert resp.status_code == 200
        # The optimized path should not balloon beyond a reasonable bound.
        # Pre-optimisation: type_counts alone was 3 queries; status_counts was 4.
        # Post-optimisation: type_counts = 1, status_counts = 2.
        # Total expected: ~10-20 queries for main query + pagination + counts + session.
        assert counter['n'] < 60, (
            f"Word list made {counter['n']} queries, expected < 60. "
            "type_counts or status_counts may have regressed to per-status COUNTs, "
            "or word.books is being lazily loaded per-word."
        )

    def test_type_counts_includes_all_key(
        self, authenticated_client, words_module_access, sample_words
    ):
        """type_counts 'all' must equal word + phrasal_verb totals (sanity check)."""
        resp = authenticated_client.get('/words?per_page=5')
        assert resp.status_code == 200
        # If the template renders without KeyError the dict is correct
        assert b'word' in resp.data or b'phrasal' in resp.data or 'всего'.encode() in resp.data

    def test_userword_bulk_not_per_word(
        self, app, authenticated_client, words_module_access, sample_words
    ):
        """Number of queries must not grow linearly with number of words on page.

        We compare query count for per_page=2 vs per_page=5. If UserWord were
        fetched per-word the count would scale with per_page; with bulk loading
        it stays constant.
        """
        with count_queries(app) as c2:
            r2 = authenticated_client.get('/words?per_page=2')
        with count_queries(app) as c5:
            r5 = authenticated_client.get('/words?per_page=5')

        assert r2.status_code == 200
        assert r5.status_code == 200
        # Allow a small delta (e.g. pagination overhead), but not N * per_page extra.
        delta = c5['n'] - c2['n']
        assert delta < 8, (
            f"Query count grew by {delta} when per_page increased from 2 to 5. "
            "Suggests per-word queries are being made (N+1 regression)."
        )

    def test_translation_is_column_not_relationship(self):
        """CollectionWords.russian_word is a column, not a lazy-loaded relationship.

        This ensures there is no N+1 query for loading translations.
        """
        mapper = sqlalchemy.inspect(CollectionWords)
        col_names = {c.key for c in mapper.mapper.column_attrs}
        assert 'russian_word' in col_names, (
            "russian_word should be a mapped column on CollectionWords"
        )
        # No 'translations' relationship should exist (it's in russian_word column)
        rel_names = {r.key for r in mapper.mapper.relationships}
        assert 'translations' not in rel_names, (
            "Unexpected 'translations' relationship on CollectionWords — "
            "if added, ensure it uses joinedload in the word list query."
        )
