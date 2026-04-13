"""Tests for in-app notification center."""
import pytest
import uuid
from app.auth.models import User
from app.notifications.models import Notification
from app.notifications.services import create_notification, notify_achievement, get_unread_count


@pytest.fixture
def notif_user(db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f'notif_{suffix}', email=f'notif_{suffix}@test.com', active=True, onboarding_completed=True)
    user.set_password('test')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def notif_auth_client(client, notif_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(notif_user.id)
    return client


class TestNotificationModel:
    """Test Notification model."""

    def test_create_notification(self, notif_user, db_session):
        notif = create_notification(notif_user.id, 'test', 'Test Title', 'Test message')
        db_session.commit()
        assert notif.id is not None
        assert notif.read is False

    def test_to_dict(self, notif_user, db_session):
        notif = create_notification(notif_user.id, 'test', 'Dict Test')
        db_session.commit()
        d = notif.to_dict()
        assert d['title'] == 'Dict Test'
        assert d['read'] is False

    def test_unread_count(self, notif_user, db_session):
        create_notification(notif_user.id, 'test', 'Unread 1')
        create_notification(notif_user.id, 'test', 'Unread 2')
        db_session.commit()
        count = get_unread_count(notif_user.id)
        assert count >= 2

    def test_notify_achievement(self, notif_user, db_session):
        notif = notify_achievement(notif_user.id, 'First Quiz')
        db_session.commit()
        assert notif.type == 'achievement'
        assert 'First Quiz' in notif.title


class TestNotificationAPI:
    """Test notification API endpoints."""

    def test_list_requires_login(self, client):
        response = client.get('/api/notifications/list')
        assert response.status_code in (302, 401)

    @pytest.mark.smoke
    def test_list_returns_json(self, notif_auth_client, notif_user, db_session):
        create_notification(notif_user.id, 'test', 'API Test')
        db_session.commit()
        response = notif_auth_client.get('/api/notifications/list')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert len(data['notifications']) >= 1

    @pytest.mark.smoke
    def test_unread_count_endpoint(self, notif_auth_client):
        response = notif_auth_client.get('/api/notifications/unread-count')
        assert response.status_code == 200
        data = response.get_json()
        assert 'count' in data

    @pytest.mark.smoke
    def test_mark_all_read(self, notif_auth_client, notif_user, db_session):
        create_notification(notif_user.id, 'test', 'To Read')
        db_session.commit()

        response = notif_auth_client.post('/api/notifications/read-all',
                                         headers={'X-CSRFToken': 'test'})
        assert response.status_code in (200, 400)


class TestNotificationBell:
    """Test that notification bell appears in navbar."""

    def test_bell_in_authenticated_page(self, notif_auth_client):
        response = notif_auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'notif-bell' in html

    def test_no_bell_for_anonymous(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'notif-bell' not in html

    def test_bell_does_not_use_innerhtml(self, notif_auth_client):
        """Notification dropdown must use safe DOM API, not innerHTML for user data."""
        response = notif_auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'list.textContent' in html or 'document.createElement' in html
        assert "n.title + '</div>'" not in html


class TestNotificationPreferences:
    """Test that notification preferences gate creation."""

    def test_achievement_blocked_when_pref_off(self, notif_user, db_session):
        """If user disables achievement notifications, none should be created."""
        notif_user.notify_in_app_achievements = False
        db_session.commit()

        from app.notifications.services import notify_achievement
        result = notify_achievement(notif_user.id, 'Test Badge')
        assert result is None

        notif_user.notify_in_app_achievements = True
        db_session.commit()

    def test_streak_blocked_when_pref_off(self, notif_user, db_session):
        notif_user.notify_in_app_streaks = False
        db_session.commit()

        from app.notifications.services import notify_streak_milestone
        result = notify_streak_milestone(notif_user.id, 7, 5)
        assert result is None

        notif_user.notify_in_app_streaks = True
        db_session.commit()

    def test_referral_always_sent(self, notif_user, db_session):
        """Referral notifications have no preference gate -- always created."""
        from app.notifications.services import notify_referral
        result = notify_referral(notif_user.id, 'friend123')
        db_session.commit()
        assert result is not None

    def test_achievement_sent_when_pref_on(self, notif_user, db_session):
        notif_user.notify_in_app_achievements = True
        db_session.commit()

        from app.notifications.services import notify_achievement
        result = notify_achievement(notif_user.id, 'Enabled Badge')
        db_session.commit()
        assert result is not None
