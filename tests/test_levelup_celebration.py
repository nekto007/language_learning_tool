"""Tests for level-up celebration API and modal."""
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
def test_user(app, db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'lvlup_{suffix}',
        email=f'lvlup_{suffix}@test.com',
        active=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    yield user
    db_session.delete(user)
    db_session.commit()


@pytest.fixture
def auth_client(client, test_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user.id)
    return client


class TestCelebrationAPI:
    """Test GET /study/api/celebrations endpoint."""

    def test_celebrations_requires_login(self, client):
        response = client.get('/study/api/celebrations')
        assert response.status_code in (302, 401)

    def test_celebrations_returns_json(self, auth_client):
        response = auth_client.get('/study/api/celebrations')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

    def test_celebrations_has_level(self, auth_client):
        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert 'level' in data
        assert isinstance(data['level'], int)

    def test_celebrations_has_total_xp(self, auth_client):
        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert 'total_xp' in data

    def test_celebrations_has_celebrations_list(self, auth_client):
        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert 'celebrations' in data
        assert isinstance(data['celebrations'], list)

    def test_celebrations_with_xp(self, app, auth_client, test_user, db_session):
        """After adding XP, level should be reflected."""
        from app.study.models import UserXP
        with app.app_context():
            xp = UserXP.get_or_create(test_user.id)
            xp.add_xp(500)  # Should reach level 3+
            db_session.commit()

        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert data['level'] >= 3
        assert data['total_xp'] >= 500


class TestLevelUpModalInBase:
    """Test that level-up modal and celebration script are in base template."""

    def test_base_has_levelup_modal(self, auth_client):
        """Authenticated page should contain level-up modal."""
        # Use grammar-lab (public page that extends base.html)
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'levelup-modal' in html

    def test_base_has_celebration_script(self, auth_client):
        """Authenticated page should contain celebration check script."""
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'api/celebrations' in html
