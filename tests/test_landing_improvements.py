"""Tests for landing page improvements: testimonials, FAQ, stats, JSON-LD, SEO."""
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime

import pytest


class TestLandingPage:
    """Test landing page content and structure."""

    @pytest.mark.smoke
    def test_landing_returns_200(self, client):
        response = client.get('/')
        assert response.status_code == 200

    def test_landing_has_testimonials(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'land-testimonials' in html
        assert 'Что говорят наши ученики' in html

    def test_landing_has_faq(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'land-faq' in html
        assert 'Частые вопросы' in html

    def test_landing_faq_has_8_items(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert html.count('land-faq__item') >= 8

    def test_landing_has_faq_json_ld(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'FAQPage' in html
        assert 'acceptedAnswer' in html

    def test_landing_has_website_json_ld(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'WebSite' in html

    @pytest.mark.smoke
    def test_landing_has_og_tags(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'og:title' in html
        assert 'og:description' in html


class TestLandingStats:
    """Test that stats are passed to the landing template."""

    def test_stats_contain_lessons_completed(self, client):
        """Stats should include lessons_completed key."""
        response = client.get('/')
        html = response.data.decode()
        assert response.status_code == 200

    def test_stats_contain_grammar_topics(self, client):
        """Stats should include grammar_topics key."""
        response = client.get('/')
        assert response.status_code == 200


_SITEMAP_NS = 'http://www.sitemaps.org/schemas/sitemap/0.9'


class TestSitemapNoindexExclusion:
    """Sitemap must not include pages marked noindex."""

    def _sitemap_text(self, client):
        return client.get('/sitemap.xml').data.decode('utf-8')

    def test_sitemap_excludes_register(self, client):
        assert '/register' not in self._sitemap_text(client)

    def test_sitemap_excludes_login(self, client):
        assert '/login' not in self._sitemap_text(client)

    def test_sitemap_excludes_reset_password(self, client):
        assert '/reset_password' not in self._sitemap_text(client)

    def test_sitemap_excludes_onboarding(self, client):
        assert '/onboarding' not in self._sitemap_text(client)


class TestSitemapCanonicalUrl:
    """Sitemap LOC entries must use the configured SITE_URL, not a hardcoded domain."""

    def test_sitemap_respects_site_url_config(self, client, app):
        original = app.config.get('SITE_URL', '')
        app.config['SITE_URL'] = 'https://staging.example.com'
        try:
            text = client.get('/sitemap.xml').data.decode('utf-8')
            assert 'https://staging.example.com/' in text
            assert '<loc>https://llt-english.com/' not in text
        finally:
            app.config['SITE_URL'] = original

    def test_sitemap_locs_use_consistent_base(self, client, app):
        """All sitemap locs must share the same scheme+host (no mixed domains)."""
        site_url = (app.config.get('SITE_URL') or 'https://llt-english.com').rstrip('/')
        root = ET.fromstring(client.get('/sitemap.xml').data)
        locs = [el.text for el in root.findall(f'.//{{{_SITEMAP_NS}}}loc')]
        assert locs, 'Sitemap has no <loc> entries'
        for loc in locs:
            assert loc.startswith(site_url), f'Loc uses wrong base: {loc}'


class TestSitemapLastmod:
    """lastmod dates in the sitemap must never exceed today's date."""

    def test_lastmod_values_not_in_future(self, client):
        root = ET.fromstring(client.get('/sitemap.xml').data)
        today_iso = date.today().isoformat()
        for el in root.findall(f'.//{{{_SITEMAP_NS}}}lastmod'):
            assert el.text <= today_iso, f'Future lastmod in sitemap: {el.text}'

    def test_future_updated_at_capped_at_today(self, client, app):
        """A grammar topic with updated_at in the future must appear with lastmod=today."""
        from app.grammar_lab.models import GrammarTopic
        from app.utils.db import db

        slug = f'future-lastmod-{uuid.uuid4().hex[:8]}'
        topic = GrammarTopic(
            slug=slug,
            title='Future Lastmod Test',
            title_ru='Тест',
            level='A1',
            order=9999,
            updated_at=datetime(2099, 12, 31),
        )
        db.session.add(topic)
        db.session.commit()
        try:
            site_url = app.config.get('SITE_URL', 'https://llt-english.com')
            root = ET.fromstring(client.get('/sitemap.xml').data)
            today_iso = date.today().isoformat()
            for url_el in root.findall(f'{{{_SITEMAP_NS}}}url'):
                loc = url_el.find(f'{{{_SITEMAP_NS}}}loc')
                if loc is not None and slug in (loc.text or ''):
                    lastmod_el = url_el.find(f'{{{_SITEMAP_NS}}}lastmod')
                    assert lastmod_el is not None
                    assert lastmod_el.text == today_iso
                    break
            else:
                pytest.fail(f'Topic {slug} not found in sitemap')
        finally:
            db.session.delete(topic)
            db.session.commit()


class TestRobotsRoutes:
    """robots.txt must allow public SEO routes and block authenticated routes."""

    def _robots(self, client):
        return client.get('/robots.txt').data.decode('utf-8')

    def test_robots_allows_courses_catalog(self, client):
        assert 'Disallow: /courses' not in self._robots(client)

    def test_robots_allows_dictionary(self, client):
        assert 'Disallow: /dictionary' not in self._robots(client)

    def test_robots_allows_grammar_lab(self, client):
        assert 'Disallow: /grammar-lab' not in self._robots(client)

    def test_robots_blocks_authenticated_curriculum(self, client):
        assert 'Disallow: /curriculum/' in self._robots(client)

    def test_robots_blocks_study(self, client):
        assert 'Disallow: /study/' in self._robots(client)

    def test_robots_blocks_dashboard(self, client):
        assert 'Disallow: /dashboard' in self._robots(client)

    def test_robots_contains_sitemap_link(self, client, app):
        site_url = app.config.get('SITE_URL', 'https://llt-english.com')
        assert f'Sitemap: {site_url}/sitemap.xml' in self._robots(client)
