"""Tests for public shared quiz deck page."""
import pytest
import uuid
from app import create_app
from app.utils.db import db as _db
from app.auth.models import User
from app.study.models import QuizDeck, QuizDeckWord
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
def shared_deck(app, db_session):
    """Create a public shared deck with words."""
    suffix = uuid.uuid4().hex[:8]

    user = User(username=f'deckowner_{suffix}', email=f'do_{suffix}@test.com', active=True)
    user.set_password('test')
    db_session.add(user)
    db_session.flush()

    deck = QuizDeck(
        title=f'Test Deck {suffix}',
        user_id=user.id,
        is_public=True,
        share_code=f'share{suffix}',
    )
    db_session.add(deck)
    db_session.flush()

    word = CollectionWords(
        english_word=f'deckword{suffix}',
        russian_word='тестовое',
        level='A2',
        frequency_rank=100,
    )
    db_session.add(word)
    db_session.flush()

    deck_word = QuizDeckWord(deck_id=deck.id, word_id=word.id)
    db_session.add(deck_word)
    db_session.commit()

    yield deck, word, user

    db_session.delete(deck_word)
    db_session.delete(word)
    db_session.delete(deck)
    db_session.delete(user)
    db_session.commit()


class TestSharedDeckPublic:
    """Test GET /study/quiz/shared/<code> for anonymous users."""

    def test_returns_200(self, client, shared_deck):
        deck, _, _ = shared_deck
        response = client.get(f'/study/quiz/shared/{deck.share_code}')
        assert response.status_code == 200

    def test_no_login_required(self, client, shared_deck):
        deck, _, _ = shared_deck
        response = client.get(f'/study/quiz/shared/{deck.share_code}')
        assert response.status_code == 200

    def test_shows_deck_title(self, client, shared_deck):
        deck, _, _ = shared_deck
        response = client.get(f'/study/quiz/shared/{deck.share_code}')
        html = response.data.decode()
        assert deck.title in html

    def test_shows_preview_words(self, client, shared_deck):
        deck, word, _ = shared_deck
        response = client.get(f'/study/quiz/shared/{deck.share_code}')
        html = response.data.decode()
        assert word.english_word in html

    def test_has_og_tags(self, client, shared_deck):
        deck, _, _ = shared_deck
        response = client.get(f'/study/quiz/shared/{deck.share_code}')
        html = response.data.decode()
        assert 'og:title' in html
        assert 'og:description' in html

    def test_has_register_cta(self, client, shared_deck):
        deck, _, _ = shared_deck
        response = client.get(f'/study/quiz/shared/{deck.share_code}')
        html = response.data.decode()
        assert 'register' in html.lower()

    def test_404_for_nonexistent(self, client):
        response = client.get('/study/quiz/shared/nonexistent99')
        assert response.status_code == 404

    def test_404_for_private_deck(self, app, client, db_session):
        suffix = uuid.uuid4().hex[:8]
        with app.app_context():
            user = User(username=f'pvt_{suffix}', email=f'pvt_{suffix}@test.com', active=True)
            user.set_password('test')
            db_session.add(user)
            db_session.flush()
            deck = QuizDeck(title='Private', user_id=user.id, is_public=False, share_code=f'pvt{suffix}')
            db_session.add(deck)
            db_session.commit()

            response = client.get(f'/study/quiz/shared/pvt{suffix}')
            assert response.status_code == 404

            db_session.delete(deck)
            db_session.delete(user)
            db_session.commit()
