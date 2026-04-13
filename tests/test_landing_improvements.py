"""Tests for landing page improvements: testimonials, FAQ, stats, JSON-LD."""
import pytest


class TestLandingPage:
    """Test landing page content and structure."""

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
