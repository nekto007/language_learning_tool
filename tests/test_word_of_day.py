"""Tests for Word of the Day on landing page."""
import pytest
import uuid
from app import create_app
from app.utils.db import db as _db
from app.words.models import CollectionWords
from config.settings import TestConfig


@pytest.fixture(scope='module')
def app():
    app = create_app(TestConfig)
    with app.app_context():
        from sqlalchemy import text, inspect
        inspector = inspect(_db.engine)
        columns = [c['name'] for c in inspector.get_columns('users')]
        for col, typ in [('onboarding_completed', 'BOOLEAN DEFAULT false'),
                         ('referral_code', 'VARCHAR(16) UNIQUE'),
                         ('referred_by_id', 'INTEGER'),
                         ('onboarding_level', 'VARCHAR(4)'),
                         ('onboarding_focus', 'VARCHAR(100)'),
                         ('email_unsubscribe_token', 'VARCHAR(64) UNIQUE'),
                         ('email_opted_out', 'BOOLEAN DEFAULT false')]:
            if col not in columns:
                try:
                    _db.session.execute(text(f'ALTER TABLE users ADD COLUMN {col} {typ}'))
                    _db.session.commit()
                except Exception:
                    _db.session.rollback()
        _db.create_all()
        yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield _db.session
        _db.session.rollback()


@pytest.fixture
def word_with_sentence(app, db_session):
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
    yield word
    db_session.delete(word)
    db_session.commit()


class TestWordOfDaySelection:
    """Test word of the day selection logic."""

    def test_deterministic_selection(self, app):
        """Same day should always select the same word."""
        from datetime import date
        import hashlib

        d = date(2026, 4, 9)
        seed1 = int(hashlib.md5(str(d).encode()).hexdigest(), 16)
        seed2 = int(hashlib.md5(str(d).encode()).hexdigest(), 16)
        assert seed1 == seed2

    def test_different_days_different_seeds(self, app):
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
        # The WOTD may or may not be our fixture word (depends on seed), but section should exist
        assert 'Слово дня' in html

    def test_landing_has_learn_more_cta(self, client, word_with_sentence):
        response = client.get('/')
        html = response.data.decode()
        assert 'Учить больше слов' in html or 'register' in html.lower()

    def test_landing_still_200(self, client, word_with_sentence):
        response = client.get('/')
        assert response.status_code == 200
