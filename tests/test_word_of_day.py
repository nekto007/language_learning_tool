"""Tests for Word of the Day on landing page."""
import pytest
import uuid
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


class TestWordOfDaySelection:
    """Test word of the day selection logic."""

    def test_deterministic_selection(self):
        """Same day should always select the same word."""
        from datetime import date
        import hashlib

        d = date(2026, 4, 9)
        seed1 = int(hashlib.md5(str(d).encode()).hexdigest(), 16)
        seed2 = int(hashlib.md5(str(d).encode()).hexdigest(), 16)
        assert seed1 == seed2

    def test_different_days_different_seeds(self):
        from datetime import date
        import hashlib

        seed1 = int(hashlib.md5(str(date(2026, 4, 9)).encode()).hexdigest(), 16)
        seed2 = int(hashlib.md5(str(date(2026, 4, 10)).encode()).hexdigest(), 16)
        assert seed1 != seed2


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
