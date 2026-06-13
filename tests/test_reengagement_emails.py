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


class TestNoneValuesInTemplates:
    """Templates must render without errors when context values are None."""

    def test_welcome_html_renders_with_none_username(self, app):
        from flask import render_template
        html = render_template('emails/welcome.html', username=None, dashboard_url=None)
        assert 'Добро пожаловать' in html
        assert 'None' not in html

    def test_welcome_txt_renders_with_none_username(self, app):
        from flask import render_template
        txt = render_template('emails/welcome.txt', username=None, dashboard_url=None)
        assert 'None' not in txt

    def test_day7_html_renders_with_none_lessons_completed(self, app):
        from flask import render_template
        html = render_template(
            'emails/reengagement/day7.html',
            username='TestUser',
            lessons_completed=None,
            site_url='https://llt-english.com',
            unsubscribe_url='https://llt-english.com/unsubscribe?token=test',
        )
        assert 'None' not in html
        assert '0' in html

    def test_day3_html_renders_with_none_username(self, app):
        from flask import render_template
        html = render_template(
            'emails/reengagement/day3.html',
            username=None,
            site_url='https://llt-english.com',
            unsubscribe_url='https://llt-english.com/unsubscribe?token=test',
        )
        assert 'None' not in html

    def test_day30_html_renders_with_none_username(self, app):
        from flask import render_template
        html = render_template(
            'emails/reengagement/day30.html',
            username=None,
            site_url='https://llt-english.com',
            unsubscribe_url='https://llt-english.com/unsubscribe?token=test',
        )
        assert 'None' not in html


class TestUnsubscribeLinksInMarketingEmails:
    """All marketing email templates must include an unsubscribe link."""

    def test_day3_has_unsubscribe(self, app):
        from flask import render_template
        html = render_template(
            'emails/reengagement/day3.html',
            username='User', site_url='https://llt-english.com',
            unsubscribe_url='https://llt-english.com/unsubscribe?token=abc',
        )
        assert 'unsubscribe' in html.lower() or 'отписаться' in html.lower()

    def test_day7_has_unsubscribe(self, app):
        from flask import render_template
        html = render_template(
            'emails/reengagement/day7.html',
            username='User', lessons_completed=5, site_url='https://llt-english.com',
            unsubscribe_url='https://llt-english.com/unsubscribe?token=abc',
        )
        assert 'unsubscribe' in html.lower() or 'отписаться' in html.lower()

    def test_day30_has_unsubscribe(self, app):
        from flask import render_template
        html = render_template(
            'emails/reengagement/day30.html',
            username='User', site_url='https://llt-english.com',
            unsubscribe_url='https://llt-english.com/unsubscribe?token=abc',
        )
        assert 'unsubscribe' in html.lower() or 'отписаться' in html.lower()

    def test_reminder_default_has_unsubscribe_when_token_given(self, app):
        """reminders/default.html shows unsubscribe link when unsubscribe_token is provided."""
        from flask import render_template
        from datetime import datetime, timezone

        class FakeUser:
            last_login = None
            username = 'User'

        html = render_template(
            'emails/reminders/default.html',
            user=FakeUser(),
            now=datetime.now(timezone.utc),
            unsubscribe_token='abc123',
        )
        assert 'отписаться' in html.lower() or 'token=abc123' in html.lower()


class TestSmtpDebugProduction:
    """SMTP debug level must default to 0 to avoid verbose output in production."""

    def test_smtp_debug_defaults_to_zero(self):
        """Verify default SMTP_DEBUG_LEVEL is 0 (no debug output by default)."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            from app.utils.email_utils import EmailSender
            sender = EmailSender()
            assert sender.smtp_debug_level == 0, (
                "SMTP_DEBUG_LEVEL must default to 0; nonzero value leaks SMTP conversation to logs in production"
            )


class TestEmailErrorLogging:
    """Email sending errors must be logged, not silently swallowed."""

    def test_smtp_failure_is_logged(self, app):
        from unittest.mock import patch
        import smtplib
        with app.app_context():
            with patch('app.utils.email_utils.logger') as mock_logger:
                with patch('app.utils.email_utils.smtplib.SMTP',
                           side_effect=smtplib.SMTPException("connection refused")):
                    from app.utils.email_utils import EmailSender
                    sender = EmailSender()
                    sender.email_host = 'smtp.example.com'
                    sender.default_from_email = 'noreply@example.com'
                    result = sender.send_email('Subj', 'to@test.com', 'welcome',
                                               {'username': 'X', 'dashboard_url': '#'})
                    assert result is False
                    assert mock_logger.exception.called, (
                        "SMTP failure must be logged via logger.exception"
                    )


class TestUnsubscribeFlow:
    """Test one-click email unsubscribe."""

    def test_unsubscribe_with_valid_token(self, app, client, db_session):
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

        # GET shows confirmation but does not opt out (prefetch-safe).
        resp_get = client.get(f'/unsubscribe?token=testtoken_{suffix}')
        assert resp_get.status_code == 200

        db_session.refresh(user)
        assert user.email_opted_out is False

        # POST actually performs the opt-out.
        resp_post = client.post('/unsubscribe', data={'token': f'testtoken_{suffix}'})
        assert resp_post.status_code == 200

        db_session.refresh(user)
        assert user.email_unsubscribe_token is None
        assert user.email_opted_out is True

    def test_unsubscribe_with_invalid_token(self, client):
        response = client.get('/unsubscribe?token=nonexistent')
        # Idempotent: unknown token shows a friendly already-done page.
        assert response.status_code == 200

    def test_unsubscribe_without_token(self, client):
        response = client.get('/unsubscribe')
        # Missing token → 400 error page (no silent failure).
        assert response.status_code == 400


class TestReengagementDedup:
    """Audit E-087: each (user, campaign) is sent at most once per local day,
    so the hourly cadence can't produce duplicates."""

    def test_job_does_not_resend_same_campaign_same_day(self, inactive_3day_user):
        from unittest.mock import patch
        from app import email_scheduler

        with patch.object(email_scheduler, 'send_day3_email', return_value=True) as m3, \
             patch.object(email_scheduler, 'send_day7_email', return_value=True), \
             patch.object(email_scheduler, 'send_day30_email', return_value=True), \
             patch.object(email_scheduler, 'is_delivery_window', return_value=True):
            email_scheduler.run_reengagement_job()
            first_calls = m3.call_count
            # Second hourly run the same day must not re-send.
            email_scheduler.run_reengagement_job()
            assert m3.call_count == first_calls

        # The target user was emailed exactly once across the two runs.
        sent_users = [c.args[0].id for c in m3.call_args_list]
        assert sent_users.count(inactive_3day_user.id) == 1

    def test_claim_is_idempotent(self, inactive_3day_user):
        from app.email_scheduler import _claim_reengagement
        assert _claim_reengagement(inactive_3day_user.id, 'day3') is True
        assert _claim_reengagement(inactive_3day_user.id, 'day3') is False
        # Different campaign is independent.
        assert _claim_reengagement(inactive_3day_user.id, 'day7') is True
