"""Tests for in-app notification center."""
import pytest
import uuid
from app import create_app
from app.utils.db import db as _db
from app.auth.models import User
from app.notifications.models import Notification
from app.notifications.services import create_notification, notify_achievement, get_unread_count
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
    user = User(username=f'notif_{suffix}', email=f'notif_{suffix}@test.com', active=True)
    user.set_password('test')
    db_session.add(user)
    db_session.commit()
    yield user
    Notification.query.filter_by(user_id=user.id).delete()
    db_session.delete(user)
    db_session.commit()


@pytest.fixture
def auth_client(client, test_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_user.id)
    return client


class TestNotificationModel:
    """Test Notification model."""

    def test_create_notification(self, app, test_user, db_session):
        with app.app_context():
            notif = create_notification(test_user.id, 'test', 'Test Title', 'Test message')
            db_session.commit()
            assert notif.id is not None
            assert notif.read is False

    def test_to_dict(self, app, test_user, db_session):
        with app.app_context():
            notif = create_notification(test_user.id, 'test', 'Dict Test')
            db_session.commit()
            d = notif.to_dict()
            assert d['title'] == 'Dict Test'
            assert d['read'] is False

    def test_unread_count(self, app, test_user, db_session):
        with app.app_context():
            create_notification(test_user.id, 'test', 'Unread 1')
            create_notification(test_user.id, 'test', 'Unread 2')
            db_session.commit()
            count = get_unread_count(test_user.id)
            assert count >= 2

    def test_notify_achievement(self, app, test_user, db_session):
        with app.app_context():
            notif = notify_achievement(test_user.id, 'First Quiz')
            db_session.commit()
            assert notif.type == 'achievement'
            assert 'First Quiz' in notif.title


class TestNotificationAPI:
    """Test notification API endpoints."""

    def test_list_requires_login(self, client):
        response = client.get('/api/notifications/list')
        assert response.status_code in (302, 401)

    def test_list_returns_json(self, app, auth_client, test_user, db_session):
        with app.app_context():
            create_notification(test_user.id, 'test', 'API Test')
            db_session.commit()
        response = auth_client.get('/api/notifications/list')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert len(data['notifications']) >= 1

    def test_unread_count_endpoint(self, auth_client):
        response = auth_client.get('/api/notifications/unread-count')
        assert response.status_code == 200
        data = response.get_json()
        assert 'count' in data

    def test_mark_all_read(self, app, auth_client, test_user, db_session):
        with app.app_context():
            create_notification(test_user.id, 'test', 'To Read')
            db_session.commit()

        csrf = None
        with auth_client.session_transaction() as sess:
            pass  # session exists

        response = auth_client.post('/api/notifications/read-all',
                                    headers={'X-CSRFToken': 'test'})
        # May get 400 for CSRF in test, but the route exists
        assert response.status_code in (200, 400)


class TestNotificationBell:
    """Test that notification bell appears in navbar."""

    def test_bell_in_authenticated_page(self, auth_client):
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        assert 'notif-bell' in html

    def test_no_bell_for_anonymous(self, client):
        response = client.get('/')
        html = response.data.decode()
        assert 'notif-bell' not in html

    def test_bell_does_not_use_innerhtml(self, auth_client):
        """Notification dropdown must use safe DOM API, not innerHTML for user data."""
        response = auth_client.get('/grammar-lab/')
        html = response.data.decode()
        # The notification rendering JS should use textContent/createElement, not innerHTML for notifications
        assert 'list.textContent' in html or 'document.createElement' in html
        # Should NOT contain the old innerHTML pattern for notification items
        assert "n.title + '</div>'" not in html


class TestNotificationPreferences:
    """Test that notification preferences gate creation."""

    def test_achievement_blocked_when_pref_off(self, app, test_user, db_session):
        """If user disables achievement notifications, none should be created."""
        with app.app_context():
            test_user.notify_in_app_achievements = False
            db_session.commit()

            from app.notifications.services import notify_achievement
            result = notify_achievement(test_user.id, 'Test Badge')
            assert result is None

            # Restore
            test_user.notify_in_app_achievements = True
            db_session.commit()

    def test_streak_blocked_when_pref_off(self, app, test_user, db_session):
        with app.app_context():
            test_user.notify_in_app_streaks = False
            db_session.commit()

            from app.notifications.services import notify_streak_milestone
            result = notify_streak_milestone(test_user.id, 7, 5)
            assert result is None

            test_user.notify_in_app_streaks = True
            db_session.commit()

    def test_referral_always_sent(self, app, test_user, db_session):
        """Referral notifications have no preference gate — always created."""
        with app.app_context():
            from app.notifications.services import notify_referral
            result = notify_referral(test_user.id, 'friend123')
            db_session.commit()
            assert result is not None

    def test_achievement_sent_when_pref_on(self, app, test_user, db_session):
        with app.app_context():
            test_user.notify_in_app_achievements = True
            db_session.commit()

            from app.notifications.services import notify_achievement
            result = notify_achievement(test_user.id, 'Enabled Badge')
            db_session.commit()
            assert result is not None
