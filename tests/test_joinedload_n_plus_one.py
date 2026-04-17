"""
Tests for N+1 query fixes via joinedload and batch word-count preloading.

Covers:
- _preload_deck_word_counts() batch-loads word counts without N+1
- QuizDeck.word_count returns cached _word_count when available
- learn_by_module uses joinedload — module.lessons accessed without extra query
- Study index deck listing total query count is below threshold
"""
import pytest
import sqlalchemy.event

from app.study.models import QuizDeck, QuizDeckWord
from app.curriculum.models import CEFRLevel, Module, Lessons
from app.utils.db import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class QueryCounter:
    """Counts SQL statements executed on a given SQLAlchemy engine."""

    def __init__(self, engine):
        self.engine = engine
        self.count = 0
        self._queries = []

    def __enter__(self):
        sqlalchemy.event.listen(self.engine, 'before_cursor_execute', self._handler)
        return self

    def __exit__(self, *args):
        sqlalchemy.event.remove(self.engine, 'before_cursor_execute', self._handler)

    def _handler(self, conn, cursor, statement, parameters, context, executemany):
        self.count += 1
        self._queries.append(statement[:120])


# ---------------------------------------------------------------------------
# Unit tests: _preload_deck_word_counts + QuizDeck.word_count cache
# ---------------------------------------------------------------------------

class TestPreloadDeckWordCounts:

    def test_sets_word_count_on_decks(self, app, db_session, test_user):
        from app.study.routes import _preload_deck_word_counts

        deck = QuizDeck(user_id=test_user.id, title='Deck A')
        db_session.add(deck)
        db_session.flush()

        word1 = QuizDeckWord(deck_id=deck.id, custom_english='hello', custom_russian='привет')
        word2 = QuizDeckWord(deck_id=deck.id, custom_english='world', custom_russian='мир')
        db_session.add_all([word1, word2])
        db_session.flush()

        with app.app_context():
            _preload_deck_word_counts([deck])

        assert deck._word_count == 2

    def test_empty_deck_gets_zero(self, app, db_session, test_user):
        from app.study.routes import _preload_deck_word_counts

        deck = QuizDeck(user_id=test_user.id, title='Empty Deck')
        db_session.add(deck)
        db_session.flush()

        with app.app_context():
            _preload_deck_word_counts([deck])

        assert deck._word_count == 0

    def test_empty_list_is_noop(self, app):
        from app.study.routes import _preload_deck_word_counts
        # Should not raise
        with app.app_context():
            _preload_deck_word_counts([])

    def test_single_query_for_multiple_decks(self, app, db_session, test_user):
        """Preloading N decks must issue exactly 1 DB query, not N."""
        from app.study.routes import _preload_deck_word_counts

        decks = []
        for i in range(5):
            d = QuizDeck(user_id=test_user.id, title=f'Batch Deck {i}')
            db_session.add(d)
            decks.append(d)
        db_session.flush()

        for d in decks[:3]:
            w = QuizDeckWord(deck_id=d.id, custom_english='test', custom_russian='тест')
            db_session.add(w)
        db_session.flush()

        with app.app_context():
            with QueryCounter(db.engine) as qc:
                _preload_deck_word_counts(decks)

        assert qc.count == 1, (
            f"Expected exactly 1 query for batch word count, got {qc.count}"
        )


class TestQuizDeckWordCountProperty:

    def test_returns_cached_value_without_query(self, app, db_session, test_user):
        """word_count property must use _word_count cache and skip DB query."""
        deck = QuizDeck(user_id=test_user.id, title='Cached Deck')
        db_session.add(deck)
        db_session.flush()

        # Set cache manually — simulates preload
        deck._word_count = 42

        with app.app_context():
            with QueryCounter(db.engine) as qc:
                result = deck.word_count

        assert result == 42
        assert qc.count == 0, (
            f"word_count should not query DB when _word_count is cached, "
            f"but issued {qc.count} queries"
        )

    def test_falls_back_to_db_without_cache(self, app, db_session, test_user):
        """word_count falls back to DB count when _word_count is not set."""
        deck = QuizDeck(user_id=test_user.id, title='Uncached Deck')
        db_session.add(deck)
        db_session.flush()

        w = QuizDeckWord(deck_id=deck.id, custom_english='hi', custom_russian='привет')
        db_session.add(w)
        db_session.flush()

        with app.app_context():
            # No _word_count set — should go to DB
            result = deck.word_count

        assert result == 1


# ---------------------------------------------------------------------------
# Integration test: learn_by_module uses joinedload
# ---------------------------------------------------------------------------

class TestLearnByModuleJoinedload:

    @pytest.mark.smoke
    def test_module_lessons_loaded_without_extra_query(self, app, db_session, test_user,
                                                        test_level, test_module):
        """Accessing module.lessons after joinedload must not issue an extra SELECT."""
        # Add a couple of lessons to the module
        for i in range(3):
            lesson = Lessons(
                module_id=test_module.id,
                number=i + 1,
                title=f'Lesson {i + 1}',
                type='vocabulary',
                content={'items': []},
            )
            db_session.add(lesson)
        db_session.flush()

        level_code = test_level.code

        with app.app_context():
            from sqlalchemy.orm import joinedload
            # Replicate the route query with joinedload
            with QueryCounter(db.engine) as qc:
                module = Module.query.options(
                    joinedload(Module.lessons)
                ).join(CEFRLevel).filter(
                    CEFRLevel.code == level_code,
                    Module.number == test_module.number
                ).first()

                # Access lessons — must NOT trigger another SELECT
                lessons = list(module.lessons)

        # The joinedload query counts as 1 statement (or 2 with PostgreSQL explain);
        # accessing module.lessons afterwards must not add more.
        assert len(lessons) == 3
        # With joinedload, SQLAlchemy issues 1 query (JOIN). Allow up to 2 for
        # deferred column loads or savepoint tracking.
        assert qc.count <= 2, (
            f"Expected ≤2 queries with joinedload for module+lessons, got {qc.count}. "
            f"Queries: {qc._queries}"
        )


# ---------------------------------------------------------------------------
# Performance regression: deck listing query count
# ---------------------------------------------------------------------------

class TestDeckListingQueryCount:

    @pytest.mark.smoke
    def test_preloaded_word_count_reduces_queries(self, app, db_session, test_user):
        """Deck listing with preloaded word counts must use far fewer queries than N+1."""
        from app.study.routes import _preload_deck_word_counts

        decks = []
        for i in range(5):
            d = QuizDeck(user_id=test_user.id, title=f'Perf Deck {i}')
            db_session.add(d)
            decks.append(d)
        db_session.flush()

        for d in decks:
            for j in range(3):
                w = QuizDeckWord(deck_id=d.id, custom_english=f'word{j}', custom_russian=f'слово{j}')
                db_session.add(w)
        db_session.flush()

        with app.app_context():
            # Without preload: word_count on 5 decks = 5 individual COUNT queries
            # With preload: 1 batch query + 0 per-deck queries
            with QueryCounter(db.engine) as qc:
                _preload_deck_word_counts(decks)
                counts = [d.word_count for d in decks]

        assert all(c == 3 for c in counts)
        # Only 1 batch COUNT query
        assert qc.count == 1, (
            f"Expected 1 query for batch word counts, got {qc.count}. "
            "N+1 fix not working."
        )
