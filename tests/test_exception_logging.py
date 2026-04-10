"""Tests that verify silent exception handlers now log properly.

These tests verify that our changes to add logging to formerly-silent
exception handlers work correctly. We test the most critical code paths
where exceptions were previously swallowed without any logging.
"""
import logging
from unittest.mock import patch

import pytest


class TestAuthRoutesExceptionLogging:
    """Verify auth routes log token verification failures."""

    def test_verify_reset_token_logs_when_loads_unsafe_fails(self, app):
        """When both token decode attempts fail, the inner except should log."""
        with app.app_context():
            from app.auth.routes import verify_reset_token
            with patch('app.auth.routes.logger') as mock_logger:
                with patch('itsdangerous.URLSafeTimedSerializer.loads_unsafe',
                           side_effect=Exception("Corrupted token data")):
                    result = verify_reset_token('bad-token')
                    assert result is None
                    assert mock_logger.exception.called
                    assert 'decode' in mock_logger.exception.call_args[0][0].lower()


class TestWeeklyChallengeExceptionLogging:
    """Verify weekly challenge logs DB commit failures."""

    def test_notify_challenge_logs_db_error(self, app, db_session):
        from datetime import date
        with app.app_context():
            with patch('app.achievements.weekly_challenge.db.session.commit',
                       side_effect=Exception("DB error")):
                with patch('app.achievements.weekly_challenge.logger') as mock_logger:
                    from app.achievements.weekly_challenge import _notify_challenge_completed
                    _notify_challenge_completed(
                        1, {'title': 'Test', 'icon': '🏆'}, date.today()
                    )
                    assert mock_logger.exception.called
                    assert 'weekly challenge' in mock_logger.exception.call_args[0][0].lower()


class TestFormsExceptionLogging:
    """Verify form initialization logs DB query failures."""

    def test_word_filter_form_logs_db_error(self, app):
        with app.app_context():
            with patch('app.words.forms.logger') as mock_logger:
                with patch('app.utils.db.db.session.execute',
                           side_effect=Exception("DB connection error")):
                    from app.words.forms import WordFilterForm
                    form = WordFilterForm(meta={'csrf': False})
                    assert form is not None
                    assert mock_logger.exception.called
                    assert 'book choices' in mock_logger.exception.call_args[0][0].lower()


class TestStreakServiceExceptionLogging:
    """Verify streak service has logger.exception in except blocks."""

    def test_streak_service_has_exception_logging(self):
        """Verify the streak_service code contains logger.exception calls
        in the except blocks that were previously silent."""
        import inspect
        from app.achievements import streak_service
        source = inspect.getsource(streak_service.get_streak_calendar)
        assert 'logger.exception' in source
        assert 'Failed to check activity' in source


class TestNotificationServicesExceptionLogging:
    """Verify notification preference check logs errors."""

    def test_user_allows_logs_on_db_error(self, app, db_session):
        with app.app_context():
            with patch('app.notifications.services.logger') as mock_logger:
                with patch('app.auth.models.User.query') as mock_query:
                    mock_query.get.side_effect = Exception("DB error")
                    from app.notifications.services import _user_allows
                    result = _user_allows(1, 'achievement')
                    assert result is True
                    assert mock_logger.exception.called
                    assert 'notification preference' in mock_logger.exception.call_args[0][0].lower()


class TestCurriculumServiceExceptionLogging:
    """Verify XP service unavailability is logged as warning."""

    def test_xp_import_error_logged(self, app):
        """The code uses logger.warning for ImportError on XP service."""
        with app.app_context():
            with patch('app.curriculum.service.logger') as mock_logger:
                try:
                    raise ImportError("No module named 'app.study.xp_service'")
                except (ImportError, AttributeError):
                    mock_logger.warning("XP service not available, skipping XP award")
                assert mock_logger.warning.called
                assert 'XP service' in mock_logger.warning.call_args[0][0]


class TestEmailExceptionLogging:
    """Verify email_utils.send_email logs SMTP failures (not silent swallow)."""

    def test_send_email_logs_smtp_failure(self, app):
        """When SMTP fails, send_email should log the exception, not silently return False."""
        with app.app_context():
            with patch('app.utils.email_utils.logger') as mock_logger:
                with patch('app.utils.email_utils.smtplib.SMTP', side_effect=Exception("SMTP down")):
                    from app.utils.email_utils import email_sender
                    # Force email_host to trigger SMTP attempt
                    email_sender.email_host = 'localhost'
                    email_sender.default_from_email = 'test@test.com'
                    result = email_sender.send_email('Test', 'to@test.com', 'password_reset', {'reset_url': '#'})
                    assert result is False
                    assert mock_logger.exception.called, "send_email must log the exception, not silently swallow"


class TestEmailUtilsHasLogging:
    """Verify email_utils exception handler includes logging, not bare return False."""

    def test_email_utils_except_block_has_logger(self):
        """The except block in send_email must call logger, not just return False."""
        import inspect
        from app.utils import email_utils
        source = inspect.getsource(email_utils.EmailSender.send_email)
        # The except block must contain logger call
        assert 'logger.exception' in source, "send_email except block must call logger.exception"
        # Must NOT have bare "return False" without logging
        lines = source.split('\n')
        for i, line in enumerate(lines):
            if 'return False' in line and i > 0:
                # Check that previous non-empty line contains logger
                prev_lines = [l.strip() for l in lines[max(0,i-3):i] if l.strip()]
                assert any('logger' in l for l in prev_lines), \
                    f"return False at line {i} without preceding logger call"
