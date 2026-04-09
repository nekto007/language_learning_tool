"""Tests for public word pages and SEO sitemap."""
import pytest
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
def sample_word(app, db_session):
    """Create a sample word for testing."""
    import uuid
    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'testword{suffix}',
        russian_word='тестовое слово',
        level='B1',
        frequency_rank=42,
        sentences='This is a test sentence.',
        item_type='word',
    )
    db_session.add(word)
    db_session.commit()
    yield word
    db_session.delete(word)
    db_session.commit()


class TestPublicWordRoute:
    """Test GET /dictionary/<word_slug> public route."""

    def test_public_word_returns_200(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        assert response.status_code == 200

    def test_public_word_no_login_required(self, client, sample_word):
        """Public word page should not redirect to login."""
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        assert response.status_code == 200
        assert b'login' not in (response.headers.get('Location', '') or '').encode()

    def test_public_word_contains_word(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert sample_word.english_word in html
        assert sample_word.russian_word in html

    def test_public_word_has_og_tags(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'og:title' in html
        assert 'og:description' in html

    def test_public_word_has_json_ld(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'application/ld+json' in html
        assert 'DefinedTerm' in html

    def test_public_word_has_cta(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'register' in html.lower() or 'auth/register' in html

    def test_public_word_404_for_nonexistent(self, client):
        response = client.get('/dictionary/nonexistentword99999')
        assert response.status_code == 404

    def test_public_word_shows_level(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert sample_word.level in html

    def test_public_word_shows_examples(self, client, sample_word):
        slug = sample_word.english_word.lower().replace(' ', '-')
        response = client.get(f'/dictionary/{slug}')
        html = response.data.decode()
        assert 'test sentence' in html


class TestSitemap:
    """Test sitemap.xml generation."""

    def test_sitemap_returns_xml(self, client):
        response = client.get('/sitemap.xml')
        assert response.status_code == 200
        assert 'application/xml' in response.content_type

    def test_sitemap_contains_root(self, client):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        assert 'https://llt-english.com/' in xml

    def test_sitemap_contains_dictionary_words(self, client, sample_word):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        slug = sample_word.english_word.lower().replace(' ', '-')
        assert f'/dictionary/{slug}' in xml

    def test_sitemap_valid_xml_structure(self, client):
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        assert '<?xml version="1.0"' in xml
        assert '<urlset' in xml
        assert '</urlset>' in xml


class TestRobotsTxt:
    """Test robots.txt."""

    def test_robots_returns_text(self, client):
        response = client.get('/robots.txt')
        assert response.status_code == 200
        assert 'text/plain' in response.content_type

    def test_robots_contains_sitemap(self, client):
        response = client.get('/robots.txt')
        text = response.data.decode()
        assert 'Sitemap:' in text
        assert 'sitemap.xml' in text
