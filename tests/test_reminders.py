"""Tests for reminders system: delivery, unsubscribe, suspended-user skip, rate limiting."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.auth.models import User
from app.reminders.models import ReminderLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db_session, **kwargs):
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        username=f'rem_{suffix}',
        email=f'rem_{suffix}@test.com',
        active=True,
        email_opted_out=False,
        notify_email_reminders=True,
        last_login=datetime.now(timezone.utc) - timedelta(days=10),
        timezone='Europe/Moscow',
    )
    defaults.update(kwargs)
    user = User(**defaults)
    user.set_password('testpass')
    db_session.add(user)
    db_session.commit()
    return user


# ---------------------------------------------------------------------------
# get_inactive_users (routes.py version)
# ---------------------------------------------------------------------------

class TestGetInactiveUsersRoute:
    def test_returns_inactive_users(self, app, db_session):
        from app.reminders.routes import get_inactive_users
        user = _make_user(db_session)
        with app.app_context():
            users = get_inactive_users(days=7)
        assert any(u.id == user.id for u in users)

    def test_skips_opted_out_users(self, app, db_session):
        from app.reminders.routes import get_inactive_users
        user = _make_user(db_session, email_opted_out=True)
        with app.app_context():
            users = get_inactive_users(days=7)
        assert not any(u.id == user.id for u in users)

    def test_skips_notify_disabled_users(self, app, db_session):
        from app.reminders.routes import get_inactive_users
        user = _make_user(db_session, notify_email_reminders=False)
        with app.app_context():
            users = get_inactive_users(days=7)
        assert not any(u.id == user.id for u in users)

    def test_skips_deactivated_users(self, app, db_session):
        from app.reminders.routes import get_inactive_users
        user = _make_user(db_session, active=False)
        with app.app_context():
            users = get_inactive_users(days=7)
        assert not any(u.id == user.id for u in users)

    def test_days_zero_returns_all_eligible(self, app, db_session):
        from app.reminders.routes import get_inactive_users
        user = _make_user(db_session, last_login=datetime.now(timezone.utc))
        with app.app_context():
            users = get_inactive_users(days=0)
        assert any(u.id == user.id for u in users)

    def test_days_zero_skips_opted_out(self, app, db_session):
        from app.reminders.routes import get_inactive_users
        user = _make_user(db_session, email_opted_out=True)
        with app.app_context():
            users = get_inactive_users(days=0)
        assert not any(u.id == user.id for u in users)


# ---------------------------------------------------------------------------
# was_recently_reminded — rate limit helper
# ---------------------------------------------------------------------------

class TestWasRecentlyReminded:
    def test_no_previous_reminder(self, app, db_session):
        from app.reminders.routes import _was_recently_reminded
        user = _make_user(db_session)
        with app.app_context():
            assert _was_recently_reminded(user.id) is False

    def test_recent_reminder_detected(self, app, db_session):
        from app.reminders.routes import _was_recently_reminded
        user = _make_user(db_session)
        log = ReminderLog(
            user_id=user.id,
            template='default',
            subject='Test',
            sent_by=user.id,
            sent_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db_session.add(log)
        db_session.commit()
        with app.app_context():
            assert _was_recently_reminded(user.id, hours=24) is True

    def test_old_reminder_not_blocked(self, app, db_session):
        from app.reminders.routes import _was_recently_reminded
        user = _make_user(db_session)
        log = ReminderLog(
            user_id=user.id,
            template='default',
            subject='Test',
            sent_by=user.id,
            sent_at=datetime.now(timezone.utc) - timedelta(hours=48),
        )
        db_session.add(log)
        db_session.commit()
        with app.app_context():
            assert _was_recently_reminded(user.id, hours=24) is False


# ---------------------------------------------------------------------------
# Unsubscribe route — no auth required
# ---------------------------------------------------------------------------

class TestUnsubscribeNoAuth:
    def test_unsubscribe_works_without_login(self, client, db_session):
        """GET /unsubscribe?token=... must work for unauthenticated users."""
        user = _make_user(db_session)
        user.email_unsubscribe_token = 'test_tok_' + uuid.uuid4().hex[:8]
        db_session.commit()

        resp = client.get(f'/unsubscribe?token={user.email_unsubscribe_token}',
                          follow_redirects=True)
        assert resp.status_code == 200
        # token cleared, opted_out set
        from app.utils.db import db as _db
        _db.session.refresh(user)
        assert user.email_opted_out is True
        assert user.email_unsubscribe_token is None

    def test_unsubscribe_invalid_token_does_not_crash(self, client):
        resp = client.get('/unsubscribe?token=nonexistent_token', follow_redirects=True)
        assert resp.status_code == 200

    def test_unsubscribe_missing_token_does_not_crash(self, client):
        resp = client.get('/unsubscribe', follow_redirects=True)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Timezone delivery window — email_scheduler
# ---------------------------------------------------------------------------

class TestDeliveryWindow:
    def test_in_window_returns_true(self, app, db_session):
        from app.email_scheduler import is_delivery_window
        user = _make_user(db_session, timezone='UTC')
        # Patch datetime so local hour is 12 (noon) — clearly in window
        with patch('app.email_scheduler.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 12, 0, 0,
                                                tzinfo=timezone.utc)
            assert is_delivery_window(user) is True

    def test_out_of_window_returns_false(self, app, db_session):
        from app.email_scheduler import is_delivery_window
        user = _make_user(db_session, timezone='UTC')
        # 2am UTC — outside 8am-8pm window
        with patch('app.email_scheduler.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 1, 1, 2, 0, 0,
                                                tzinfo=timezone.utc)
            assert is_delivery_window(user) is False

    def test_invalid_timezone_falls_back_to_utc(self, app, db_session):
        from app.email_scheduler import is_delivery_window
        user = _make_user(db_session, timezone='Not/A/Timezone')
        # Should not raise, falls back to UTC
        result = is_delivery_window(user)
        assert isinstance(result, bool)

    def test_none_timezone_falls_back_to_utc(self, app, db_session):
        from app.email_scheduler import is_delivery_window
        user = _make_user(db_session, timezone=None)
        result = is_delivery_window(user)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# send_reminders admin endpoint — skip suspended/opted-out users
# ---------------------------------------------------------------------------

class TestSendRemindersEndpoint:
    def test_skips_opted_out_user(self, client, db_session, admin_user):
        """Opted-out user should not receive reminder even when selected."""
        user = _make_user(db_session, email_opted_out=True)

        with patch('app.reminders.routes.send_email') as mock_send:
            resp = client.post('/admin/reminders/send', data={
                'user_ids': [str(user.id)],
                'reminder_template': 'default',
                'custom_subject': 'Test',
            })
        mock_send.assert_not_called()

    def test_skips_notify_disabled_user(self, client, db_session, admin_user):
        """User with notify_email_reminders=False should be skipped."""
        user = _make_user(db_session, notify_email_reminders=False)

        with patch('app.reminders.routes.send_email') as mock_send:
            resp = client.post('/admin/reminders/send', data={
                'user_ids': [str(user.id)],
                'reminder_template': 'default',
                'custom_subject': 'Test',
            })
        mock_send.assert_not_called()

    def test_skips_deactivated_user(self, client, db_session, admin_user):
        """Deactivated (suspended) user should not receive reminder."""
        user = _make_user(db_session, active=False)

        with patch('app.reminders.routes.send_email') as mock_send:
            resp = client.post('/admin/reminders/send', data={
                'user_ids': [str(user.id)],
                'reminder_template': 'default',
                'custom_subject': 'Test',
            })
        mock_send.assert_not_called()

    def test_skips_recently_reminded_user(self, client, db_session, admin_user):
        """User who received a reminder in the last 24h should be skipped."""
        user = _make_user(db_session)
        log = ReminderLog(
            user_id=user.id,
            template='default',
            subject='Recent',
            sent_by=admin_user.id,
            sent_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add(log)
        db_session.commit()

        with patch('app.reminders.routes.send_email') as mock_send:
            resp = client.post('/admin/reminders/send', data={
                'user_ids': [str(user.id)],
                'reminder_template': 'default',
                'custom_subject': 'Test',
            })
        mock_send.assert_not_called()

    def test_invalid_template_name_returns_redirect(self, client, db_session, admin_user):
        """Template names with path traversal chars must be rejected."""
        user = _make_user(db_session)

        resp = client.post('/admin/reminders/send', data={
            'user_ids': [str(user.id)],
            'reminder_template': '../../../etc/passwd',
            'custom_subject': 'Test',
        }, follow_redirects=False)
        # Should redirect (flash error), not render template
        assert resp.status_code in (302, 303)
