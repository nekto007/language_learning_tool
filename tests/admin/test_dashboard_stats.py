"""Tests for admin dashboard statistics queries."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.utils.db import db


class TestGetDashboardStatistics:
    """Tests for get_dashboard_statistics function."""

    def test_returns_expected_keys(self, app, db_session):
        """Dashboard stats dict should contain all expected keys."""
        from app.admin.main_routes import get_dashboard_statistics

        with patch('app.admin.main_routes.cache_result', lambda *a, **kw: lambda f: f):
            stats = get_dashboard_statistics()

        expected_keys = {
            'total_users', 'active_users', 'new_users', 'active_recently',
            'total_books', 'total_readings', 'words_total', 'words_with_audio',
            'total_lessons', 'active_lessons'
        }
        assert expected_keys.issubset(stats.keys())

    def test_counts_users_correctly(self, app, db_session):
        """Should count total, active, new, and recently active users."""
        now = datetime.now(timezone.utc)

        # Create users with different states
        u1 = User(
            username=f'active_{uuid.uuid4().hex[:8]}',
            email=f'a_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now - timedelta(days=1),
            last_login=now - timedelta(hours=1),
        )
        u1.set_password('pass')

        u2 = User(
            username=f'inactive_{uuid.uuid4().hex[:8]}',
            email=f'i_{uuid.uuid4().hex[:8]}@test.com',
            active=False,
            created_at=now - timedelta(days=30),
            last_login=now - timedelta(days=20),
        )
        u2.set_password('pass')

        u3 = User(
            username=f'new_{uuid.uuid4().hex[:8]}',
            email=f'n_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now - timedelta(days=2),
            last_login=now - timedelta(days=2),
        )
        u3.set_password('pass')

        db_session.add_all([u1, u2, u3])
        db_session.commit()

        from app.admin.main_routes import get_dashboard_statistics
        stats = get_dashboard_statistics.__wrapped__()

        assert stats['total_users'] == 3
        assert stats['active_users'] == 2  # u1 and u3
        assert stats['new_users'] >= 2  # u1 and u3 created within 7 days
        assert stats['active_recently'] >= 2  # u1 and u3 logged in within 7 days


class TestGetDailyActivityData:
    """Tests for get_daily_activity_data function."""

    def test_returns_correct_structure(self, app, db_session):
        """Should return dict with labels, registrations, logins, active_users."""
        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__(7)

        assert 'labels' in result
        assert 'registrations' in result
        assert 'logins' in result
        assert 'active_users' in result
        assert len(result['labels']) == 7
        assert len(result['registrations']) == 7
        assert len(result['logins']) == 7
        assert len(result['active_users']) == 7

    def test_counts_registrations(self, app, db_session):
        """Should count registrations per day."""
        now = datetime.now(timezone.utc)
        today = now.date()

        u = User(
            username=f'reg_{uuid.uuid4().hex[:8]}',
            email=f'reg_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.commit()

        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__(7)

        # Last element should be today
        assert result['labels'][-1] == today.strftime('%d.%m')
        # At least 1 registration today
        assert result['registrations'][-1] >= 1

    def test_counts_logins(self, app, db_session):
        """Should count logins per day."""
        now = datetime.now(timezone.utc)

        u = User(
            username=f'login_{uuid.uuid4().hex[:8]}',
            email=f'login_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
            created_at=now - timedelta(days=10),
            last_login=now,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.commit()

        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__(7)

        assert result['logins'][-1] >= 1

    def test_counts_active_users_from_lesson_progress(self, app, db_session):
        """Should count active users who had lesson progress activity."""
        now = datetime.now(timezone.utc)

        u = User(
            username=f'lp_{uuid.uuid4().hex[:8]}',
            email=f'lp_{uuid.uuid4().hex[:8]}@test.com',
            active=True,
        )
        u.set_password('pass')
        db_session.add(u)
        db_session.flush()

        level = CEFRLevel(
            code=uuid.uuid4().hex[:2].upper(),
            name='Test', description='Test', order=1
        )
        db_session.add(level)
        db_session.flush()

        module = Module(level_id=level.id, number=1, title='Test Module')
        db_session.add(module)
        db_session.flush()

        lesson = Lessons(module_id=module.id, number=1, title='Test', type='text', order=1)
        db_session.add(lesson)
        db_session.flush()

        lp = LessonProgress(
            user_id=u.id,
            lesson_id=lesson.id,
            status='completed',
            last_activity=now,
        )
        db_session.add(lp)
        db_session.commit()

        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__(7)

        assert result['active_users'][-1] >= 1

    def test_default_30_days(self, app, db_session):
        """Default call should return 30 days of data."""
        from app.admin.main_routes import get_daily_activity_data

        result = get_daily_activity_data.__wrapped__()

        assert len(result['labels']) == 30


class TestDashboardRoute:
    """Tests for the admin dashboard route."""

    def test_dashboard_returns_200(self, app, client, admin_user):
        """Admin dashboard should return 200 for admin user."""
        response = client.get('/admin/')
        assert response.status_code == 200

    def test_dashboard_contains_activity_data(self, app, client, admin_user):
        """Dashboard should contain activity chart labels in rendered HTML."""
        response = client.get('/admin/')
        assert response.status_code == 200
        data = response.data.decode('utf-8')
        # Chart should have real labels (date format dd.mm)
        assert 'activityLabels' in data
        assert 'activityRegistrations' in data
        assert 'activityActiveUsers' in data

    def test_dashboard_shows_total_readings(self, app, client, admin_user):
        """Dashboard should display total_readings stat."""
        response = client.get('/admin/')
        data = response.data.decode('utf-8')
        assert 'Уникальных слов в книгах' in data
