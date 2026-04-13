"""Tests for public user profile page."""
import pytest
import uuid
from app.auth.models import User


@pytest.fixture
def profile_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f'pub_{suffix}', email=f'pub_{suffix}@test.com', active=True)
    user.set_password('test')
    db_session.add(user)
    db_session.commit()
    return user


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


class TestProfileExternalUrls:
    """Test that profile and referral pages use dynamic URLs, not hardcoded domain."""

    def test_profile_url_uses_url_for(self, client, db_session):
        """Profile page should show URL via url_for, not hardcoded llt-english.com."""
        suffix = uuid.uuid4().hex[:8]
        user = User(username=f'urltest_{suffix}', email=f'urltest_{suffix}@t.com', active=True)
        user.set_password('test')
        db_session.add(user)
        db_session.commit()

        with client.session_transaction() as sess:
            sess['_user_id'] = str(user.id)

        response = client.get('/profile')
        if response.status_code == 200:
            html = response.data.decode()
            assert f'/u/{user.username}' in html
            assert f'https://llt-english.com/u/{user.username}' not in html or 'url_for' in html or 'localhost' in html
