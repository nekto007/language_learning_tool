"""Tests for SEO blueprint: sitemap.xml and robots.txt."""
import uuid
import xml.etree.ElementTree as ET

import pytest

from app.grammar_lab.models import GrammarTopic
from app.utils.db import db


@pytest.fixture
def grammar_topic(app, db_session):
    """Create a test grammar topic for sitemap tests."""
    topic = GrammarTopic(
        slug=f'test-seo-{uuid.uuid4().hex[:8]}',
        title='Test Topic',
        title_ru='Тестовая тема',
        level='A1',
        order=1,
    )
    db.session.add(topic)
    db.session.commit()
    yield topic
    db.session.delete(topic)
    db.session.commit()


class TestSitemap:
    @pytest.mark.smoke
    def test_sitemap_returns_xml(self, client):
        response = client.get('/sitemap.xml')
        assert response.status_code == 200
        assert 'application/xml' in response.content_type

    def test_sitemap_valid_xml(self, client):
        response = client.get('/sitemap.xml')
        root = ET.fromstring(response.data)
        assert root.tag == '{http://www.sitemaps.org/schemas/sitemap/0.9}urlset'

    def test_sitemap_contains_static_pages(self, client, app):
        response = client.get('/sitemap.xml')
        xml_text = response.data.decode('utf-8')
        site_url = app.config.get('SITE_URL', 'https://llt-english.com')
        assert f'{site_url}/' in xml_text
        assert f'{site_url}/grammar-lab/topics' in xml_text
        # /register is intentionally excluded — register.html sets noindex,
        # so listing it in sitemap would trigger GSC "submitted URL marked noindex" warnings.
        assert f'{site_url}/register' not in xml_text

    def test_sitemap_contains_grammar_topics(self, client, app, grammar_topic):
        response = client.get('/sitemap.xml')
        xml_text = response.data.decode('utf-8')
        site_url = app.config.get('SITE_URL', 'https://llt-english.com')
        assert f'{site_url}/grammar-lab/topic/{grammar_topic.id}' in xml_text

    def test_sitemap_uses_single_configured_host(self, client, app):
        original_site_url = app.config.get('SITE_URL', '')
        app.config['SITE_URL'] = 'https://staging.llt-english.com'
        try:
            response = client.get('/sitemap.xml')
            xml_text = response.data.decode('utf-8')

            assert '<loc>https://staging.llt-english.com/' in xml_text
            assert '<loc>https://llt-english.com/' not in xml_text
        finally:
            app.config['SITE_URL'] = original_site_url


class TestRobots:
    @pytest.mark.smoke
    def test_robots_returns_text(self, client):
        response = client.get('/robots.txt')
        assert response.status_code == 200
        assert response.content_type == 'text/plain; charset=utf-8'

    def test_robots_allows_all(self, client):
        response = client.get('/robots.txt')
        text = response.data.decode('utf-8')
        assert 'User-agent: *' in text
        assert 'Allow: /' in text

    def test_robots_disallows_admin(self, client):
        response = client.get('/robots.txt')
        text = response.data.decode('utf-8')
        assert 'Disallow: /admin/' in text

    def test_robots_contains_sitemap(self, client, app):
        response = client.get('/robots.txt')
        text = response.data.decode('utf-8')
        site_url = app.config.get('SITE_URL', 'https://llt-english.com')
        assert f'Sitemap: {site_url}/sitemap.xml' in text

    def test_robots_uses_single_configured_sitemap_host(self, client, app):
        original_site_url = app.config.get('SITE_URL', '')
        app.config['SITE_URL'] = 'https://staging.llt-english.com'
        try:
            response = client.get('/robots.txt')
            text = response.data.decode('utf-8')

            assert 'Sitemap: https://staging.llt-english.com/sitemap.xml' in text
            assert 'Sitemap: https://llt-english.com/sitemap.xml' not in text
        finally:
            app.config['SITE_URL'] = original_site_url
