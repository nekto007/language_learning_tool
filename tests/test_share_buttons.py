"""Tests for share buttons rendering on public pages."""
import pytest
from app import create_app
from app.utils.db import db as _db
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
def sample_grammar_topic(app, db_session):
    """Create a sample grammar topic."""
    import uuid
    from app.grammar_lab.models import GrammarTopic
    suffix = uuid.uuid4().hex[:8]
    topic = GrammarTopic(
        slug=f'test-share-{suffix}',
        title=f'Test Share Topic {suffix}',
        title_ru=f'Тестовая тема {suffix}',
        level='B1',
        order=999,
        content={'introduction': 'Test content'},
    )
    db_session.add(topic)
    db_session.commit()
    yield topic
    db_session.delete(topic)
    db_session.commit()


class TestShareButtonsOnGrammarTopic:
    """Test share buttons on grammar topic detail page."""

    def test_grammar_topic_has_share_buttons(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn' in html

    def test_grammar_topic_has_telegram_share(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn--telegram' in html

    def test_grammar_topic_has_whatsapp_share(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn--whatsapp' in html

    def test_grammar_topic_has_twitter_share(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn--twitter' in html

    def test_grammar_topic_has_copy_button(self, client, sample_grammar_topic):
        response = client.get(f'/grammar-lab/topic/{sample_grammar_topic.id}')
        html = response.data.decode()
        assert 'share-btn--copy' in html


class TestShareJS:
    """Test that share.js is loaded."""

    def test_share_js_included_in_base(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'share.js' in html
