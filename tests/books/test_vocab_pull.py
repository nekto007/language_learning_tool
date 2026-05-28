"""Unit tests for app.books.vocab_pull."""
from datetime import datetime, timezone

import pytest

from app.books.vocab_pull import STOP_WORDS, extract_chapter_vocab, queue_vocab_as_srs
from app.utils.db import db


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def book(db_session):
    from app.books.models import Book
    b = Book(title='VP Test Book', author='Author', level='A1', chapters_cnt=1)
    db_session.add(b)
    db_session.flush()
    return b


@pytest.fixture()
def chapter(db_session, book):
    from app.books.models import Chapter
    text = (
        'The quick brown fox jumps over the lazy dog. '
        'Complicated vocabulary requires practice everyday. '
        'Understanding grammar concepts becomes easier through reading.'
    )
    ch = Chapter(book_id=book.id, chap_num=1, title='Ch1', words=30, text_raw=text)
    db_session.add(ch)
    db_session.flush()
    return ch


@pytest.fixture()
def word_factory(db_session):
    """Return a factory that creates CollectionWords rows."""
    from app.words.models import CollectionWords

    def _make(english_word, frequency_rank=None):
        w = CollectionWords(english_word=english_word, russian_word=f'{english_word}_ru',
                            frequency_rank=frequency_rank)
        db_session.add(w)
        db_session.flush()
        return w

    return _make


# ---------------------------------------------------------------------------
# STOP_WORDS sanity check
# ---------------------------------------------------------------------------

class TestStopWords:
    def test_common_function_words_in_stop_list(self):
        for w in ('the', 'and', 'is', 'to', 'of', 'in', 'it', 'you', 'we', 'they'):
            assert w in STOP_WORDS, f"'{w}' should be in STOP_WORDS"

    def test_content_words_not_in_stop_list(self):
        for w in ('vocabulary', 'practice', 'grammar', 'reading', 'understanding'):
            assert w not in STOP_WORDS, f"'{w}' should NOT be in STOP_WORDS"


# ---------------------------------------------------------------------------
# extract_chapter_vocab
# ---------------------------------------------------------------------------

class TestExtractChapterVocab:
    def test_returns_empty_for_missing_chapter(self, app, db_session, test_user):
        result = extract_chapter_vocab(99999, 0.0, 1.0, test_user.id, db)
        assert result == []

    @pytest.mark.smoke
    def test_returns_matched_words(self, app, db_session, test_user, chapter, word_factory):
        word_factory('vocabulary', frequency_rank=500)
        word_factory('practice', frequency_rank=600)
        db_session.commit()

        result = extract_chapter_vocab(chapter.id, 0.0, 1.0, test_user.id, db)
        english_words = [w.english_word for w in result]
        assert 'vocabulary' in english_words
        assert 'practice' in english_words

    def test_stop_words_are_filtered(self, app, db_session, test_user, chapter, word_factory):
        # 'the' is a stop word - even if it exists in DB it should be excluded
        word_factory('the', frequency_rank=1)
        db_session.commit()

        result = extract_chapter_vocab(chapter.id, 0.0, 1.0, test_user.id, db)
        english_words = [w.english_word for w in result]
        assert 'the' not in english_words

    def test_already_known_words_skipped(self, app, db_session, test_user, chapter, word_factory):
        from app.study.models import UserWord
        vocab_word = word_factory('vocabulary', frequency_rank=500)
        practice_word = word_factory('practice', frequency_rank=600)
        db_session.commit()

        # Mark vocabulary as already known
        uw = UserWord.get_or_create(test_user.id, vocab_word.id)
        db_session.commit()

        result = extract_chapter_vocab(chapter.id, 0.0, 1.0, test_user.id, db)
        english_words = [w.english_word for w in result]
        assert 'vocabulary' not in english_words
        assert 'practice' in english_words

    def test_respects_count_limit(self, app, db_session, test_user, chapter, word_factory):
        # Create several words that appear in chapter text
        for rank, name in enumerate(
            ['vocabulary', 'practice', 'grammar', 'reading', 'understanding'], start=100
        ):
            word_factory(name, frequency_rank=rank)
        db_session.commit()

        result = extract_chapter_vocab(chapter.id, 0.0, 1.0, test_user.id, db, count=2)
        assert len(result) <= 2

    def test_sorted_by_frequency_rank_asc(self, app, db_session, test_user, chapter, word_factory):
        # Lower rank number = more frequent
        vocab = word_factory('vocabulary', frequency_rank=200)
        practice = word_factory('practice', frequency_rank=100)
        db_session.commit()

        result = extract_chapter_vocab(chapter.id, 0.0, 1.0, test_user.id, db, count=2)
        assert len(result) == 2
        assert result[0].frequency_rank <= result[1].frequency_rank

    def test_offset_slice_limits_text(self, app, db_session, test_user, book, word_factory):
        """Word only in first half should not appear when we slice second half."""
        from app.books.models import Chapter
        text = 'vocabulary vocabulary vocabulary ' + ('practice ' * 30)
        ch = Chapter(book_id=book.id, chap_num=2, title='Ch2', words=40, text_raw=text)
        db_session.add(ch)

        vocab_word = word_factory('vocabulary', frequency_rank=50)
        db_session.commit()

        # Slice second half only — 'vocabulary' should not appear
        result = extract_chapter_vocab(ch.id, 0.5, 1.0, test_user.id, db)
        english_words = [w.english_word for w in result]
        assert 'vocabulary' not in english_words

    def test_inverted_offsets_returns_list(self, app, db_session, test_user, chapter, word_factory):
        word_factory('vocabulary', frequency_rank=500)
        db_session.commit()

        result = extract_chapter_vocab(chapter.id, 0.8, 0.3, test_user.id, db)
        assert isinstance(result, list)

    def test_returns_empty_when_no_matches_in_db(self, app, db_session, test_user, chapter):
        # No CollectionWords in DB for chapter text words
        result = extract_chapter_vocab(chapter.id, 0.0, 1.0, test_user.id, db)
        assert result == []


# ---------------------------------------------------------------------------
# queue_vocab_as_srs
# ---------------------------------------------------------------------------

class TestQueueVocabAsSrs:
    def test_empty_words_returns_zero(self, app, db_session, test_user):
        count = queue_vocab_as_srs([], test_user.id, db)
        assert count == 0

    @pytest.mark.smoke
    def test_creates_two_cards_per_word(self, app, db_session, test_user, word_factory):
        from app.study.models import UserCardDirection, UserWord
        w = word_factory('reading', frequency_rank=300)
        db_session.commit()

        created = queue_vocab_as_srs([w], test_user.id, db)
        db_session.commit()

        assert created == 2
        uw = UserWord.query.filter_by(user_id=test_user.id, word_id=w.id).first()
        assert uw is not None
        cards = UserCardDirection.query.filter_by(user_word_id=uw.id).all()
        assert len(cards) == 2
        directions = {c.direction for c in cards}
        assert 'eng-rus' in directions
        assert 'rus-eng' in directions

    def test_next_review_is_tomorrow_or_later(self, app, db_session, test_user, word_factory):
        from app.study.models import UserCardDirection, UserWord
        w = word_factory('understanding', frequency_rank=400)
        db_session.commit()

        queue_vocab_as_srs([w], test_user.id, db)
        db_session.commit()

        uw = UserWord.query.filter_by(user_id=test_user.id, word_id=w.id).first()
        cards = UserCardDirection.query.filter_by(user_word_id=uw.id).all()
        now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        for card in cards:
            assert card.next_review is not None
            assert card.next_review >= now_naive

    def test_source_is_book_reading(self, app, db_session, test_user, word_factory):
        from app.study.models import UserCardDirection, UserWord
        w = word_factory('grammar', frequency_rank=250)
        db_session.commit()

        queue_vocab_as_srs([w], test_user.id, db)
        db_session.commit()

        uw = UserWord.query.filter_by(user_id=test_user.id, word_id=w.id).first()
        cards = UserCardDirection.query.filter_by(user_word_id=uw.id).all()
        for card in cards:
            assert card.source == 'book_reading'

    @pytest.mark.smoke
    def test_idempotent_no_duplicate_cards(self, app, db_session, test_user, word_factory):
        from app.study.models import UserCardDirection, UserWord
        w = word_factory('concepts', frequency_rank=700)
        db_session.commit()

        first = queue_vocab_as_srs([w], test_user.id, db)
        db_session.commit()
        second = queue_vocab_as_srs([w], test_user.id, db)
        db_session.commit()

        assert first == 2
        assert second == 0  # already exists — no new cards

        uw = UserWord.query.filter_by(user_id=test_user.id, word_id=w.id).first()
        total = UserCardDirection.query.filter_by(user_word_id=uw.id).count()
        assert total == 2

    def test_multiple_words(self, app, db_session, test_user, word_factory):
        from app.study.models import UserCardDirection, UserWord
        w1 = word_factory('easier', frequency_rank=800)
        w2 = word_factory('requires', frequency_rank=900)
        db_session.commit()

        created = queue_vocab_as_srs([w1, w2], test_user.id, db)
        db_session.commit()

        assert created == 4
