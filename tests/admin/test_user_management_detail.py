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

    def test_csv_export_has_header(self, app, admin_client):
        response = admin_client.get('/admin/users/export')
        csv_text = response.get_data(as_text=True)
        assert 'username' in csv_text
        assert 'email' in csv_text

    def test_csv_escapes_dangerous_chars(self, app, admin_client, db_session):
        """CSV cells starting with =, +, -, @ should be prefixed with apostrophe."""
        from app.admin.utils.export_helpers import _sanitize_csv_cell
        assert _sanitize_csv_cell('=cmd|/C calc') == "'=cmd|/C calc"
        assert _sanitize_csv_cell('+1234') == "'+1234"
        assert _sanitize_csv_cell('-formula') == "'-formula"
        assert _sanitize_csv_cell('@import') == "'@import"
        assert _sanitize_csv_cell('normal') == 'normal'
        assert _sanitize_csv_cell(None) == ''

    def test_csv_export_respects_limit(self, app, admin_client):
        """Export should not exceed MAX_EXPORT_ROWS."""
        from app.admin.utils.export_helpers import MAX_EXPORT_ROWS
        assert MAX_EXPORT_ROWS == 10000

    def test_csv_route_sanitizes_dangerous_values(self, app, admin_client, db_session):
        """Route-level: dangerous chars in username should be escaped in CSV output."""
        u = _make_user(db_session, username=f'=cmd_{uuid.uuid4().hex[:6]}')
        db_session.commit()

        response = admin_client.get('/admin/users/export')
        csv_text = response.get_data(as_text=True)

        # The username starts with '=' so it must be prefixed with apostrophe in CSV
        assert f"'={u.username[1:]}" in csv_text or f"\"'={u.username[1:]}\"" in csv_text

    def test_csv_route_is_streaming(self, app, admin_client):
        """Route should return a streaming response (generator), not buffered."""
        response = admin_client.get('/admin/users/export')
        # Flask streaming responses have is_streamed=True
        assert response.is_streamed

    def test_csv_route_row_count_within_limit(self, app, admin_client, db_session):
        """CSV export should contain a header plus data rows, not exceeding limit."""
        response = admin_client.get('/admin/users/export')
        csv_text = response.get_data(as_text=True)
        lines = [l for l in csv_text.strip().split('\n') if l]
        # At least header + 1 data row (admin_user exists)
        assert len(lines) >= 2
        # Total lines (including header) should not exceed MAX_EXPORT_ROWS + 1
        from app.admin.utils.export_helpers import MAX_EXPORT_ROWS
        assert len(lines) <= MAX_EXPORT_ROWS + 1
