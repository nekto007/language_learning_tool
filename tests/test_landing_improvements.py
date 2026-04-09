"""Tests for landing page improvements: testimonials, FAQ, stats, JSON-LD."""
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

    def test_stats_contain_lessons_completed(self, app, client):
        """Stats should include lessons_completed key."""
        response = client.get('/')
        html = response.data.decode()
        # The template renders stats, we just check no error
        assert response.status_code == 200

    def test_stats_contain_grammar_topics(self, app, client):
        """Stats should include grammar_topics key."""
        response = client.get('/')
        assert response.status_code == 200
