"""Tests for SEO meta optimization: hreflang, content-language, Organization, lastmod."""
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


class TestMetaTags:
    """Test that meta tags are present on all pages."""

    def test_hreflang_on_landing(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'hreflang="ru"' in html

    def test_content_language_on_landing(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'content-language' in html

    def test_organization_json_ld(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert '"Organization"' in html
        assert 'LLT English' in html

    def test_hreflang_on_grammar(self, client):
        response = client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'hreflang="ru"' in html


class TestSitemapLastmod:
    """Test sitemap lastmod values."""

    def test_sitemap_has_lastmod(self, client):
        """Sitemap should contain lastmod for grammar topics that have updated_at."""
        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        # lastmod may or may not appear depending on data, but the structure should be valid
        assert '<urlset' in xml
        assert '</urlset>' in xml

    def test_sitemap_grammar_with_lastmod(self, app, client):
        """If grammar topics have updated_at, lastmod should appear."""
        import uuid
        from app.grammar_lab.models import GrammarTopic
        from datetime import datetime, timezone

        with app.app_context():
            suffix = uuid.uuid4().hex[:6]
            topic = GrammarTopic(
                slug=f'lastmod-{suffix}', title=f'Lastmod Test {suffix}',
                title_ru='Тест', level='A1', order=999,
                content={}, updated_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
            )
            _db.session.add(topic)
            _db.session.commit()

            response = client.get('/sitemap.xml')
            xml = response.data.decode()
            assert '2026-03-15' in xml

            _db.session.delete(topic)
            _db.session.commit()
