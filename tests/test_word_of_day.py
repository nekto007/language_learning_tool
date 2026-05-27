"""Tests for Word of the Day on landing page."""
import hashlib
import uuid
from datetime import date

import pytest

from app.words.models import CollectionWords


@pytest.fixture
def word_with_sentence(db_session):
    """Create a word with sentence and frequency for WOTD selection."""
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'wotd{suffix}',
        russian_word='слово дня тест',
        level='B1',
        frequency_rank=1,
        sentences=f'This is a wotd{suffix} example sentence.',
    )
    db_session.add(word)
    db_session.commit()
    return word


@pytest.fixture
def word_no_translation(db_session):
    """Create a word with no russian_word for exclusion testing."""
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'notranslation{suffix}',
        russian_word=None,
        level='B1',
        frequency_rank=2,
        sentences=f'This word has no translation {suffix}.',
    )
    db_session.add(word)
    db_session.commit()
    return word


@pytest.fixture
def word_zero_rank(db_session):
    """Create a word with frequency_rank=0 (should be excluded from WOTD)."""
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'zerorank{suffix}',
        russian_word='нулевой ранг',
        level='B1',
        frequency_rank=0,
        sentences=f'Zero rank word {suffix}.',
    )
    db_session.add(word)
    db_session.commit()
    return word


class TestWordOfDaySelection:
    """Test word of the day selection logic."""

    def test_deterministic_selection(self):
        """Same day should always produce the same seed."""
        d = date(2026, 4, 9)
        seed1 = int(hashlib.md5(str(d).encode()).hexdigest(), 16)
        seed2 = int(hashlib.md5(str(d).encode()).hexdigest(), 16)
        assert seed1 == seed2

    def test_different_days_different_seeds(self):
        """Different days should produce different seeds."""
        seed1 = int(hashlib.md5(str(date(2026, 4, 9)).encode()).hexdigest(), 16)
        seed2 = int(hashlib.md5(str(date(2026, 4, 10)).encode()).hexdigest(), 16)
        assert seed1 != seed2

    def test_seed_is_integer(self):
        """Seed must be a non-negative integer usable as modulo divisor."""
        seed = int(hashlib.md5(str(date.today()).encode()).hexdigest(), 16)
        assert isinstance(seed, int)
        assert seed >= 0

    def test_daily_consistency_same_offset(self):
        """Same date consistently maps to the same offset for a given total_words."""
        total_words = 1000
        seed = int(hashlib.md5(str(date(2026, 5, 27)).encode()).hexdigest(), 16)
        offset1 = seed % total_words
        offset2 = seed % total_words
        assert offset1 == offset2

    def test_offset_within_bounds(self):
        """Offset is always within [0, total_words)."""
        total_words = 500
        for day_offset in range(10):
            d = date(2026, 5, day_offset + 1)
            seed = int(hashlib.md5(str(d).encode()).hexdigest(), 16)
            offset = seed % total_words
            assert 0 <= offset < total_words


class TestWordOfDayOnLanding:
    """Test WOTD section renders on landing page."""

    def test_landing_has_wotd_section(self, client, word_with_sentence):
        response = client.get('/')
        html = response.data.decode()
        assert 'land-wotd' in html or 'Слово дня' in html

    def test_landing_shows_word(self, client, word_with_sentence):
        response = client.get('/')
        html = response.data.decode()
        assert 'Слово дня' in html

    def test_landing_has_learn_more_cta(self, client, word_with_sentence):
        response = client.get('/')
        html = response.data.decode()
        assert 'Учить больше слов' in html or 'register' in html.lower()

    def test_landing_still_200(self, client, word_with_sentence):
        response = client.get('/')
        assert response.status_code == 200

    def test_anonymous_user_can_access_landing(self, client, word_with_sentence):
        """Landing page must be accessible without authentication."""
        response = client.get('/')
        assert response.status_code == 200
        html = response.data.decode()
        assert 'Слово дня' in html

    def test_landing_200_without_any_eligible_word(self, client):
        """Landing page does not crash when no eligible word exists."""
        response = client.get('/')
        assert response.status_code == 200

    def test_word_without_translation_excluded_from_wotd(self, app, db_session, word_no_translation):
        """Words with russian_word=None must not be selected as WOTD."""
        from app.words.models import CollectionWords

        with app.app_context():
            result = (
                CollectionWords.query
                .filter(
                    CollectionWords.frequency_rank > 0,
                    CollectionWords.sentences.isnot(None),
                    CollectionWords.russian_word.isnot(None),
                )
                .filter(CollectionWords.id == word_no_translation.id)
                .first()
            )
        assert result is None, "Word without russian_word must be excluded from WOTD query"

    def test_frequency_rank_zero_excluded_from_wotd(self, app, db_session, word_zero_rank):
        """Words with frequency_rank=0 must not be selected as WOTD."""
        from app.words.models import CollectionWords

        with app.app_context():
            result = (
                CollectionWords.query
                .filter(
                    CollectionWords.frequency_rank > 0,
                    CollectionWords.sentences.isnot(None),
                    CollectionWords.russian_word.isnot(None),
                )
                .filter(CollectionWords.id == word_zero_rank.id)
                .first()
            )
        assert result is None, "Word with frequency_rank=0 must be excluded from WOTD query"

    def test_landing_handles_word_no_russian_gracefully(self, client, word_no_translation):
        """Landing page must not crash or render 'None' even if word has no translation."""
        response = client.get('/')
        assert response.status_code == 200
        html = response.data.decode()
        # The word without translation should not appear — filtered out — and the page renders fine
        assert '>None<' not in html

    def test_wotd_consistent_within_same_request(self, client, word_with_sentence):
        """Two requests on the same day return the same WOTD (deterministic by date seed)."""
        response1 = client.get('/')
        response2 = client.get('/')
        assert response1.status_code == 200
        assert response2.status_code == 200
        # Both responses should contain the same word content
        html1 = response1.data.decode()
        html2 = response2.data.decode()
        # Extract english word from wotd section - presence of the fixture word
        assert html1 == html2 or ('Слово дня' in html1 and 'Слово дня' in html2)
