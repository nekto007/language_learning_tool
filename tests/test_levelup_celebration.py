"""Tests for level-up celebration API and modal."""
import pytest
import uuid
from app.auth.models import User


@pytest.fixture
def celebration_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'lvlup_{suffix}',
        email=f'lvlup_{suffix}@test.com',
        active=True,
        onboarding_completed=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def auth_client(client, celebration_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(celebration_user.id)
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

    def test_celebrations_with_xp(self, auth_client, celebration_user, db_session):
        """After adding XP, level should be reflected."""
        from app.achievements.models import UserStatistics
        stats = UserStatistics.query.filter_by(user_id=celebration_user.id).first()
        if stats is None:
            stats = UserStatistics(user_id=celebration_user.id, total_xp=500)
            db_session.add(stats)
        else:
            stats.total_xp = 500
        db_session.commit()

        response = auth_client.get('/study/api/celebrations')
        data = response.get_json()
        assert data['level'] >= 3
        assert data['total_xp'] >= 500


class TestLevelUpModalInBase:
    """Test that level-up modal and celebration script are in base template."""

    def test_base_has_levelup_modal(self, auth_client):
        """Authenticated page should contain level-up modal."""
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'levelup-modal' in html

    def test_base_has_celebration_script(self, auth_client):
        """Authenticated page should contain celebration check script."""
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'api/celebrations' in html
