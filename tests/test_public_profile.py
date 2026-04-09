"""Tests for public user profile page."""
import pytest
import uuid
from app import create_app
from app.utils.db import db as _db
from app.auth.models import User
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
def profile_user(app, db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f'pub_{suffix}', email=f'pub_{suffix}@test.com', active=True)
    user.set_password('test')
    db_session.add(user)
    db_session.commit()
    yield user
    db_session.delete(user)
    db_session.commit()


class TestPublicProfile:
    """Test GET /u/<username> public route."""

    def test_returns_200(self, client, profile_user):
        response = client.get(f'/u/{profile_user.username}')
        assert response.status_code == 200

    def test_no_login_required(self, client, profile_user):
        response = client.get(f'/u/{profile_user.username}')
        assert response.status_code == 200

    def test_404_for_nonexistent(self, client):
        response = client.get('/u/nonexistent_user_99999')
        assert response.status_code == 404

    def test_shows_username(self, client, profile_user):
        response = client.get(f'/u/{profile_user.username}')
        html = response.data.decode()
        assert profile_user.username in html

    def test_has_og_tags(self, client, profile_user):
        response = client.get(f'/u/{profile_user.username}')
        html = response.data.decode()
        assert 'og:title' in html
        assert 'og:description' in html

    def test_has_json_ld(self, client, profile_user):
        response = client.get(f'/u/{profile_user.username}')
        html = response.data.decode()
        assert 'ProfilePage' in html

    def test_has_share_buttons(self, client, profile_user):
        response = client.get(f'/u/{profile_user.username}')
        html = response.data.decode()
        assert 'share-btn' in html

    def test_shows_register_cta_for_anonymous(self, client, profile_user):
        response = client.get(f'/u/{profile_user.username}')
        html = response.data.decode()
        assert 'register' in html.lower()

    def test_shows_level_and_xp(self, client, profile_user):
        response = client.get(f'/u/{profile_user.username}')
        html = response.data.decode()
        assert 'Level' in html or 'Уровень' in html
        assert 'XP' in html
