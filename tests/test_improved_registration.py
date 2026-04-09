"""Tests for improved registration flow."""
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


class TestRegistrationPage:
    """Test registration page improvements."""

    def test_register_returns_200(self, client):
        response = client.get('/register')
        assert response.status_code == 200

    def test_register_with_level_param(self, client):
        response = client.get('/register?level=B1')
        html = response.data.decode()
        assert response.status_code == 200
        assert 'B1' in html  # level preserved in form action

    def test_register_with_ref_param(self, client):
        response = client.get('/register?ref=abc123')
        html = response.data.decode()
        assert response.status_code == 200
        assert 'abc123' in html  # ref preserved as hidden input

    def test_social_proof_counter(self, client):
        """Register page should show learner count."""
        response = client.get('/register')
        html = response.data.decode()
        assert 'ученикам' in html or 'social-proof' in html

    def test_register_preserves_both_params(self, client):
        response = client.get('/register?level=A2&ref=xyz789')
        html = response.data.decode()
        assert 'A2' in html
        assert 'xyz789' in html
