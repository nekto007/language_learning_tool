"""Tests for public streak page and calendar data."""
import pytest
import uuid
from datetime import date, timedelta
from app import create_app
from app.utils.db import db as _db
from app.auth.models import User
from app.achievements.models import StreakEvent
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
def streak_user(app, db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f'strk_{suffix}', email=f'strk_{suffix}@test.com', active=True)
    user.set_password('test')
    db_session.add(user)
    db_session.flush()

    # Add 5 consecutive days of activity
    today = date.today()
    for i in range(5):
        db_session.add(StreakEvent(
            user_id=user.id, event_type='earned_daily',
            coins_delta=1, event_date=today - timedelta(days=i),
        ))
    db_session.commit()
    yield user
    StreakEvent.query.filter_by(user_id=user.id).delete()
    db_session.delete(user)
    db_session.commit()


class TestStreakCalendarData:
    """Test get_streak_calendar function."""

    def test_returns_active_dates(self, app, streak_user):
        from app.achievements.streak_service import get_streak_calendar
        with app.app_context():
            cal = get_streak_calendar(streak_user.id)
            assert cal['total_active_days'] >= 5

    def test_current_streak(self, app, streak_user):
        from app.achievements.streak_service import get_streak_calendar
        with app.app_context():
            cal = get_streak_calendar(streak_user.id)
            assert cal['current_streak'] >= 5

    def test_longest_streak(self, app, streak_user):
        from app.achievements.streak_service import get_streak_calendar
        with app.app_context():
            cal = get_streak_calendar(streak_user.id)
            assert cal['longest_streak'] >= 5


class TestPublicStreakPage:
    """Test GET /streak/<username> route."""

    def test_returns_200(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        assert response.status_code == 200

    def test_no_login_required(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        assert response.status_code == 200

    def test_404_for_nonexistent(self, client):
        response = client.get('/streak/nonexistent_user_99999')
        assert response.status_code == 404

    def test_shows_streak_count(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        html = response.data.decode()
        assert 'strk-hero' in html
        assert streak_user.username in html

    def test_has_og_tags(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        html = response.data.decode()
        assert 'og:title' in html

    def test_has_share_buttons(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        html = response.data.decode()
        assert 'share-btn' in html

    def test_has_register_cta(self, client, streak_user):
        response = client.get(f'/streak/{streak_user.username}')
        html = response.data.decode()
        assert 'register' in html.lower()
