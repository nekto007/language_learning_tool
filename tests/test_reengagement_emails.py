"""Tests for re-engagement email scheduler logic and unsubscribe flow."""
import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
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
def inactive_3day_user(app, db_session):
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
    yield user
    db_session.delete(user)
    db_session.commit()


class TestGetInactiveUsers:
    """Test inactive user detection logic."""

    def test_finds_3day_inactive(self, app, inactive_3day_user):
        with app.app_context():
            from app.email_scheduler import get_inactive_users
            users = get_inactive_users(3)
            usernames = [u.username for u in users]
            assert inactive_3day_user.username in usernames

    def test_excludes_opted_out_users(self, app, db_session):
        """Users who unsubscribed should not receive emails."""
        suffix = uuid.uuid4().hex[:8]
        with app.app_context():
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

            db_session.delete(user)
            db_session.commit()

    def test_no_false_positives_for_active_users(self, app, db_session):
        """Recently active user should not be found."""
        suffix = uuid.uuid4().hex[:8]
        with app.app_context():
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

            db_session.delete(user)
            db_session.commit()


class TestEmailRendering:
    """Test that email templates render without errors."""

    def test_day3_template_renders(self, app):
        with app.app_context():
            from flask import render_template
            html = render_template('emails/reengagement/day3.html',
                                 username='TestUser', site_url='https://llt-english.com',
                                 unsubscribe_url='https://llt-english.com/unsubscribe?token=test')
            assert 'TestUser' in html
            assert 'unsubscribe' in html.lower()

    def test_day7_template_renders(self, app):
        with app.app_context():
            from flask import render_template
            html = render_template('emails/reengagement/day7.html',
                                 username='TestUser', lessons_completed=15,
                                 site_url='https://llt-english.com',
                                 unsubscribe_url='https://llt-english.com/unsubscribe?token=test')
            assert 'TestUser' in html
            assert '15' in html

    def test_day30_template_renders(self, app):
        with app.app_context():
            from flask import render_template
            html = render_template('emails/reengagement/day30.html',
                                 username='TestUser', site_url='https://llt-english.com',
                                 unsubscribe_url='https://llt-english.com/unsubscribe?token=test')
            assert 'TestUser' in html
            assert 'нового' in html.lower()


class TestUnsubscribeFlow:
    """Test one-click email unsubscribe."""

    def test_unsubscribe_with_valid_token(self, app, client, db_session):
        suffix = uuid.uuid4().hex[:8]
        with app.app_context():
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
            assert response.status_code == 302  # Redirect

            # Token should be cleared and opted out
            db_session.refresh(user)
            assert user.email_unsubscribe_token is None
            assert user.email_opted_out is True

            db_session.delete(user)
            db_session.commit()

    def test_unsubscribe_with_invalid_token(self, client):
        response = client.get('/unsubscribe?token=nonexistent')
        assert response.status_code == 302  # Redirect with error flash

    def test_unsubscribe_without_token(self, client):
        response = client.get('/unsubscribe')
        assert response.status_code == 302
