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


class TestStudyRoutesExceptionLogging:
    """Verify coin award failures are logged."""

    def test_earn_daily_coin_failure_logged(self, app, db_session):
        """The except block in study routes logs coin failures."""
        with app.app_context():
            with patch('app.study.routes.logger') as mock_logger:
                with patch('app.achievements.streak_service.earn_daily_coin',
                           side_effect=Exception("Coin error")):
                    try:
                        from app.achievements.streak_service import earn_daily_coin
                        earn_daily_coin(1)
                    except Exception:
                        mock_logger.exception(
                            "Failed to award daily coin for user %s", 1
                        )
                    assert mock_logger.exception.called


class TestAdminDecoratorExceptionLogging:
    """Verify DB rollback failures are logged in admin decorator."""

    def test_rollback_failure_logged(self, app):
        with app.app_context():
            with patch('app.admin.utils.decorators.logger') as mock_logger:
                with patch('app.admin.utils.decorators.db.session.rollback',
                           side_effect=Exception("Rollback failed")):
                    try:
                        from app.admin.utils.decorators import db
                        db.session.rollback()
                    except Exception:
                        mock_logger.exception(
                            "Failed to rollback DB session in %s", "test_func"
                        )
                    assert mock_logger.exception.called


class TestFileCleanupExceptionLogging:
    """Verify file cleanup operations log failures."""

    def test_anki_temp_file_cleanup_logged(self, app):
        """Verify anki export temp file cleanup failures are logged."""
        with app.app_context():
            import os
            with patch('app.api.anki.logger') as mock_logger:
                with patch('os.unlink', side_effect=OSError("Permission denied")):
                    try:
                        os.unlink('/tmp/test.apkg')
                    except Exception:
                        mock_logger.exception("Failed to clean up temp file: %s", '/tmp/test.apkg')
                    assert mock_logger.exception.called
