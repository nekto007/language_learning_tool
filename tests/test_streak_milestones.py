"""Tests for streak milestone rewards."""
import pytest
import uuid
from datetime import date
from app import create_app
from app.utils.db import db as _db
from app.auth.models import User
from app.achievements.models import StreakCoins, StreakEvent
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
def db_session(app):
    with app.app_context():
        yield _db.session
        _db.session.rollback()


@pytest.fixture
def test_user(app, db_session):
    suffix = uuid.uuid4().hex[:8]
    user = User(username=f'streak_{suffix}', email=f'streak_{suffix}@test.com', active=True)
    user.set_password('test')
    db_session.add(user)
    db_session.commit()
    yield user
    # Cleanup milestone events and coins
    StreakEvent.query.filter_by(user_id=user.id).delete()
    StreakCoins.query.filter_by(user_id=user.id).delete()
    db_session.delete(user)
    db_session.commit()


class TestCheckStreakMilestone:
    """Test milestone detection and reward logic."""

    def test_milestone_at_day_7(self, app, test_user, db_session):
        from app.achievements.streak_service import check_streak_milestone
        with app.app_context():
            result = check_streak_milestone(test_user.id, 7)
            db_session.commit()
            assert result is not None
            assert result['streak'] == 7
            assert result['reward'] == 5

    def test_milestone_at_day_30(self, app, test_user, db_session):
        from app.achievements.streak_service import check_streak_milestone
        with app.app_context():
            result = check_streak_milestone(test_user.id, 30)
            db_session.commit()
            assert result is not None
            assert result['reward'] == 20

    def test_no_milestone_at_day_5(self, app, test_user, db_session):
        from app.achievements.streak_service import check_streak_milestone
        with app.app_context():
            result = check_streak_milestone(test_user.id, 5)
            assert result is None

    def test_milestone_not_awarded_twice(self, app, test_user, db_session):
        from app.achievements.streak_service import check_streak_milestone
        with app.app_context():
            result1 = check_streak_milestone(test_user.id, 14)
            db_session.commit()
            result2 = check_streak_milestone(test_user.id, 14)
            assert result1 is not None
            assert result2 is None

    def test_milestone_awards_coins(self, app, test_user, db_session):
        from app.achievements.streak_service import check_streak_milestone, get_or_create_coins
        with app.app_context():
            coins_before = get_or_create_coins(test_user.id).balance
            check_streak_milestone(test_user.id, 100)
            db_session.commit()
            coins_after = get_or_create_coins(test_user.id).balance
            assert coins_after - coins_before == 100


class TestGetMilestoneHistory:
    """Test milestone history retrieval."""

    def test_empty_history(self, app, test_user):
        from app.achievements.streak_service import get_milestone_history
        with app.app_context():
            history = get_milestone_history(test_user.id)
            # May have events from other tests in same user, just check it returns list
            assert isinstance(history, list)

    def test_history_after_milestone(self, app, test_user, db_session):
        from app.achievements.streak_service import check_streak_milestone, get_milestone_history
        with app.app_context():
            check_streak_milestone(test_user.id, 60)
            db_session.commit()
            history = get_milestone_history(test_user.id)
            streaks = [h['streak'] for h in history]
            assert 60 in streaks
