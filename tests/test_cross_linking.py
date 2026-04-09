"""Tests for cross-linking between words and grammar topics."""
import pytest
import uuid
from app import create_app
from app.utils.db import db as _db
from app.words.models import CollectionWords
from app.grammar_lab.models import GrammarTopic
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
def cross_link_data(app, db_session):
    """Create a word and grammar topic at the same level."""
    suffix = uuid.uuid4().hex[:6]
    word = CollectionWords(
        english_word=f'crossword{suffix}',
        russian_word='кроссворд тест',
        level='B2',
        frequency_rank=50,
        sentences=f'Example with crossword{suffix}.',
    )
    topic = GrammarTopic(
        slug=f'cross-topic-{suffix}',
        title=f'Cross Topic {suffix}',
        title_ru=f'Кросс тема {suffix}',
        level='B2',
        order=950,
        content={'introduction': 'Cross link test'},
    )
    db_session.add_all([word, topic])
    db_session.commit()
    yield word, topic
    db_session.delete(word)
    db_session.delete(topic)
    db_session.commit()


class TestWordToGrammarCrossLink:
    """Test that public word page shows grammar topics of same level."""

    def test_word_page_has_grammar_section(self, client, cross_link_data):
        word, topic = cross_link_data
        slug = word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'Grammar Lab' in html or 'grammar-lab' in html.lower() or 'Грамматика' in html

    def test_word_page_has_continue_learning(self, client, cross_link_data):
        word, _ = cross_link_data
        slug = word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'courses/' in html or 'grammar-lab' in html


class TestGrammarToWordCrossLink:
    """Test that grammar topic page shows vocabulary of same level."""

    def test_grammar_page_has_vocabulary_section(self, client, cross_link_data):
        _, topic = cross_link_data
        response = client.get(f'/grammar-lab/topic/{topic.id}')
        html = response.data.decode()
        assert 'Словарь уровня' in html or 'dictionary/' in html

    def test_grammar_page_has_continue_learning(self, client, cross_link_data):
        _, topic = cross_link_data
        response = client.get(f'/grammar-lab/topic/{topic.id}')
        html = response.data.decode()
        assert 'Курс' in html and topic.level in html
