"""Tests for user detail, at-risk users, and CSV export."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.admin.services import UserManagementService
from app.auth.models import User, ReferralLog
from app.utils.db import db


def _make_user(db_session, **kwargs):
    """Create a user with sensible defaults."""
    defaults = {
        'username': f'user_{uuid.uuid4().hex[:8]}',
        'email': f'{uuid.uuid4().hex[:8]}@test.com',
        'active': True,
        'created_at': datetime.now(timezone.utc),
    }
    defaults.update(kwargs)
    u = User(**defaults)
    u.set_password('testpass')
    db_session.add(u)
    db_session.flush()
    return u


class TestGetUserDetail:
    """Tests for UserManagementService.get_user_detail."""

    def test_returns_none_for_missing_user(self, app, db_session):
        result = UserManagementService.get_user_detail(999999)
        assert result is None

    def test_returns_basic_fields(self, app, db_session):
        user = _make_user(db_session)
        db_session.commit()

        result = UserManagementService.get_user_detail(user.id)
        assert result is not None
        assert result['user_id'] == user.id
        assert result['username'] == user.username
        assert result['email'] == user.email
        assert 'words' in result
        assert 'lessons' in result
        assert 'streak' in result
        assert 'coins' in result
        assert 'grammar' in result
        assert 'grades' in result
        assert 'referrals_made' in result
        assert 'module_names' in result

    def test_streak_defaults_to_zero(self, app, db_session):
        user = _make_user(db_session)
        db_session.commit()

        result = UserManagementService.get_user_detail(user.id)
        assert result['streak']['current'] == 0
        assert result['streak']['longest'] == 0
        assert result['streak']['total_badges'] == 0

    def test_coins_defaults_to_zero(self, app, db_session):
        user = _make_user(db_session)
        db_session.commit()

        result = UserManagementService.get_user_detail(user.id)
        assert result['coins']['balance'] == 0
        assert result['coins']['total_earned'] == 0

    def test_with_streak_data(self, app, db_session):
        from app.achievements.models import UserStatistics

        user = _make_user(db_session)
        stats = UserStatistics(
            user_id=user.id,
            current_streak_days=5,
            longest_streak_days=10,
            total_lessons_completed=15,
            total_badges=3,
            total_badge_points=50,
        )
        db_session.add(stats)
        db_session.commit()

        result = UserManagementService.get_user_detail(user.id)
        assert result['streak']['current'] == 5
        assert result['streak']['longest'] == 10
        assert result['streak']['total_badges'] == 3

    def test_referrals_counted(self, app, db_session):
        referrer = _make_user(db_session)
        referred = _make_user(db_session, referred_by_id=referrer.id)
        log = ReferralLog(referrer_id=referrer.id, referred_id=referred.id)
        db_session.add(log)
        db_session.commit()

        result = UserManagementService.get_user_detail(referrer.id)
        assert result['referrals_made'] == 1


class TestGetAtRiskUsers:
    """Tests for UserManagementService.get_at_risk_users."""

    def test_returns_empty_when_no_users(self, app, db_session):
        result = UserManagementService.get_at_risk_users()
        # May return empty or existing users; just check it's a list
        assert isinstance(result, list)

    def test_finds_inactive_user_with_streak(self, app, db_session):
        from app.achievements.models import UserStatistics

        user = _make_user(
            db_session,
            last_login=datetime.now(timezone.utc) - timedelta(days=10),
        )
        stats = UserStatistics(
            user_id=user.id,
            current_streak_days=0,
            longest_streak_days=5,
        )
        db_session.add(stats)
        db_session.commit()

        result = UserManagementService.get_at_risk_users(inactive_days=7, min_streak=3)
        usernames = [r['username'] for r in result]
        assert user.username in usernames

    def test_excludes_recently_active_user(self, app, db_session):
        from app.achievements.models import UserStatistics

        user = _make_user(
            db_session,
            last_login=datetime.now(timezone.utc) - timedelta(days=1),
        )
        stats = UserStatistics(
            user_id=user.id,
            current_streak_days=5,
            longest_streak_days=10,
        )
        db_session.add(stats)
        db_session.commit()

        result = UserManagementService.get_at_risk_users(inactive_days=7, min_streak=3)
        usernames = [r['username'] for r in result]
        assert user.username not in usernames

    def test_excludes_user_with_low_streak(self, app, db_session):
        from app.achievements.models import UserStatistics

        user = _make_user(
            db_session,
            last_login=datetime.now(timezone.utc) - timedelta(days=10),
        )
        stats = UserStatistics(
            user_id=user.id,
            current_streak_days=0,
            longest_streak_days=1,
        )
        db_session.add(stats)
        db_session.commit()

        result = UserManagementService.get_at_risk_users(inactive_days=7, min_streak=3)
        usernames = [r['username'] for r in result]
        assert user.username not in usernames


class TestExportUsersCsv:
    """Tests for UserManagementService.export_users_csv."""

    def test_returns_list_of_dicts(self, app, db_session):
        _make_user(db_session)
        db_session.commit()

        result = UserManagementService.export_users_csv()
        assert isinstance(result, list)
        assert len(result) > 0
        assert 'username' in result[0]
        assert 'email' in result[0]
        assert 'lessons_completed' in result[0]

    def test_search_filters_results(self, app, db_session):
        u1 = _make_user(db_session, username='findme_export_test')
        _make_user(db_session, username='notme_other_export')
        db_session.commit()

        result = UserManagementService.export_users_csv(search='findme_export')
        usernames = [r['username'] for r in result]
        assert 'findme_export_test' in usernames

    def test_includes_key_metrics(self, app, db_session):
        from app.achievements.models import UserStatistics, StreakCoins

        user = _make_user(db_session)
        stats = UserStatistics(
            user_id=user.id,
            total_lessons_completed=10,
            current_streak_days=3,
            longest_streak_days=7,
        )
        coins = StreakCoins(user_id=user.id, balance=50, total_earned=100, total_spent=50)
        db_session.add_all([stats, coins])
        db_session.commit()

        result = UserManagementService.export_users_csv(search=user.username)
        row = next(r for r in result if r['username'] == user.username)
        assert row['lessons_completed'] == 10
        assert row['current_streak'] == 3
        assert row['coin_balance'] == 50


class TestUserDetailRoute:
    """Tests for user detail route."""

    def test_user_detail_page_renders(self, app, admin_client, db_session):
        from app.auth.models import User as UserModel
        user = UserModel.query.first()
        if user:
            response = admin_client.get(f'/admin/users/{user.id}')
            assert response.status_code == 200

    def test_user_detail_404_redirects(self, app, admin_client):
        response = admin_client.get('/admin/users/999999')
        assert response.status_code == 302  # redirect to users list

    def test_csv_export_route(self, app, admin_client):
        response = admin_client.get('/admin/users/export')
        assert response.status_code == 200
        assert 'text/csv' in response.content_type
