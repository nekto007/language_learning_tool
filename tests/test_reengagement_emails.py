"""Tests for re-engagement email scheduler logic and unsubscribe flow."""
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from app.auth.models import User


@pytest.fixture
def inactive_3day_user(db_session):
    """User who was last active 3 days ago."""
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f'day3_{suffix}',
        email=f'day3_{suffix}@test.com',
        active=True,
        last_login=datetime.now(timezone.utc) - timedelta(days=3),
    )
    user.set_password('test')
    db_session.add(user)
    db_session.commit()
    return user


class TestGetInactiveUsers:
    """Test inactive user detection logic."""

    def test_finds_3day_inactive(self, inactive_3day_user):
        from app.email_scheduler import get_inactive_users
        users = get_inactive_users(3)
        usernames = [u.username for u in users]
        assert inactive_3day_user.username in usernames

    def test_excludes_opted_out_users(self, db_session):
        """Users who unsubscribed should not receive emails."""
        suffix = uuid.uuid4().hex[:8]
        user = User(
            username=f'optout_{suffix}',
            email=f'optout_{suffix}@test.com',
            active=True,
            email_opted_out=True,
            last_login=datetime.now(timezone.utc) - timedelta(days=3),
        )
        user.set_password('test')
        db_session.add(user)
        db_session.commit()

        from app.email_scheduler import get_inactive_users
        users = get_inactive_users(3)
        usernames = [u.username for u in users]
        assert user.username not in usernames

    def test_no_false_positives_for_active_users(self, db_session):
        """Recently active user should not be found."""
        suffix = uuid.uuid4().hex[:8]
        user = User(
            username=f'active_{suffix}',
            email=f'active_{suffix}@test.com',
            active=True,
            last_login=datetime.now(timezone.utc),
        )
        user.set_password('test')
        db_session.add(user)
        db_session.commit()

        from app.email_scheduler import get_inactive_users
        users = get_inactive_users(3)
        usernames = [u.username for u in users]
        assert user.username not in usernames


class TestEmailRendering:
    """Test that email templates render without errors."""

    def test_day3_template_renders(self, app):
        from flask import render_template
        html = render_template('emails/reengagement/day3.html',
                             username='TestUser', site_url='https://llt-english.com',
                             unsubscribe_url='https://llt-english.com/unsubscribe?token=test')
        assert 'TestUser' in html
        assert 'unsubscribe' in html.lower()

    def test_day7_template_renders(self, app):
        from flask import render_template
        html = render_template('emails/reengagement/day7.html',
                             username='TestUser', lessons_completed=15,
                             site_url='https://llt-english.com',
                             unsubscribe_url='https://llt-english.com/unsubscribe?token=test')
        assert 'TestUser' in html
        assert '15' in html

    def test_day30_template_renders(self, app):
        from flask import render_template
        html = render_template('emails/reengagement/day30.html',
                             username='TestUser', site_url='https://llt-english.com',
                             unsubscribe_url='https://llt-english.com/unsubscribe?token=test')
        assert 'TestUser' in html
        assert 'нового' in html.lower()


class TestUnsubscribeFlow:
    """Test one-click email unsubscribe."""

    def test_unsubscribe_with_valid_token(self, client, db_session):
        suffix = uuid.uuid4().hex[:8]
        user = User(
            username=f'unsub_{suffix}',
            email=f'unsub_{suffix}@test.com',
            active=True,
            email_unsubscribe_token=f'testtoken_{suffix}',
        )
        user.set_password('test')
        db_session.add(user)
        db_session.commit()

        response = client.get(f'/unsubscribe?token=testtoken_{suffix}')
        assert response.status_code == 302

        db_session.refresh(user)
        assert user.email_unsubscribe_token is None
        assert user.email_opted_out is True

    def test_unsubscribe_with_invalid_token(self, client):
        response = client.get('/unsubscribe?token=nonexistent')
        assert response.status_code == 302

    def test_unsubscribe_without_token(self, client):
        response = client.get('/unsubscribe')
        assert response.status_code == 302
