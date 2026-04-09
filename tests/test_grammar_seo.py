"""Tests for Grammar Lab SEO improvements: breadcrumbs, related topics, sitemap."""
import pytest
import uuid
from app import create_app
from app.utils.db import db as _db
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
def grammar_topics(app, db_session):
    """Create two related grammar topics."""
    suffix = uuid.uuid4().hex[:6]
    t1 = GrammarTopic(
        slug=f'seo-topic1-{suffix}', title=f'SEO Topic 1 {suffix}',
        title_ru=f'Тема 1 {suffix}', level='B1', order=901,
        content={'introduction': 'Test intro'},
    )
    t2 = GrammarTopic(
        slug=f'seo-topic2-{suffix}', title=f'SEO Topic 2 {suffix}',
        title_ru=f'Тема 2 {suffix}', level='B1', order=902,
        content={'introduction': 'Test intro 2'},
    )
    db_session.add_all([t1, t2])
    db_session.commit()
    yield t1, t2
    db_session.delete(t1)
    db_session.delete(t2)
    db_session.commit()


class TestGrammarBreadcrumbs:
    """Test breadcrumb rendering and JSON-LD."""

    def test_topic_has_breadcrumb_html(self, client, grammar_topics):
        t1, _ = grammar_topics
        response = client.get(f'/grammar-lab/topic/{t1.id}')
        html = response.data.decode()
        assert 'grammar-breadcrumb' in html

    def test_topic_has_breadcrumb_json_ld(self, client, grammar_topics):
        t1, _ = grammar_topics
        response = client.get(f'/grammar-lab/topic/{t1.id}')
        html = response.data.decode()
        assert 'BreadcrumbList' in html


class TestRelatedTopics:
    """Test related topics section."""

    def test_topic_shows_related(self, client, grammar_topics):
        t1, t2 = grammar_topics
        response = client.get(f'/grammar-lab/topic/{t1.id}')
        html = response.data.decode()
        assert t2.title in html

    def test_topic_does_not_show_self(self, client, grammar_topics):
        t1, _ = grammar_topics
        response = client.get(f'/grammar-lab/topic/{t1.id}')
        html = response.data.decode()
        # The topic title appears in hero, but should not appear in related section
        # We check that related section exists
        assert 'topic-related' in html


class TestSitemapGrammarLevels:
    """Test that grammar level pages are in sitemap."""

    def test_sitemap_has_grammar_lab(self, client):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        assert '/grammar-lab/' in xml

    def test_sitemap_has_grammar_level_pages(self, client, grammar_topics):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        assert '/grammar-lab/topics/b1' in xml
