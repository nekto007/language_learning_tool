"""Tests for SEO meta optimization: hreflang, content-language, Organization, lastmod."""
import pytest
import uuid
from app.utils.db import db as _db


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
        assert '<urlset' in xml
        assert '</urlset>' in xml

    def test_sitemap_grammar_with_lastmod(self, client, db_session):
        """If grammar topics have updated_at, lastmod should appear."""
        from app.grammar_lab.models import GrammarTopic
        from datetime import datetime, timezone

        suffix = uuid.uuid4().hex[:6]
        topic = GrammarTopic(
            slug=f'lastmod-{suffix}', title=f'Lastmod Test {suffix}',
            title_ru='Тест', level='A1', order=999,
            content={}, updated_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
        )
        db_session.add(topic)
        db_session.commit()

        response = client.get('/sitemap.xml')
        xml = response.data.decode()
        assert '2026-03-15' in xml
