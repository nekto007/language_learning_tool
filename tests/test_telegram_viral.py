"""Tests for Telegram bot viral features: /invite, referral stats in /stats, weekly prompt."""
import pytest
from unittest.mock import patch, MagicMock
from app import create_app
from app.utils.db import db as _db
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


class TestInviteCommand:
    """Test /invite command handler."""

    def test_handle_invite_no_user(self, app):
        """Should tell unlinked users to link first."""
        with app.app_context():
            from app.telegram.bot import _handle_invite
            with patch('app.telegram.bot._send_message') as mock_send:
                _handle_invite(123, 99999999)
                mock_send.assert_called_once()
                assert 'привяжи' in mock_send.call_args[0][1].lower()

    def test_handle_invite_linked_user(self, app, db_session):
        """Should return invite message with referral link."""
        import uuid
        from app.auth.models import User
        from app.telegram.models import TelegramUser

        with app.app_context():
            suffix = uuid.uuid4().hex[:8]
            user = User(username=f'inv_{suffix}', email=f'inv_{suffix}@t.com', active=True)
            user.set_password('test')
            db_session.add(user)
            db_session.flush()

            tg = TelegramUser(user_id=user.id, telegram_id=88880000 + int(suffix[:4], 16), is_active=True)
            db_session.add(tg)
            db_session.commit()

            from app.telegram.bot import _handle_invite
            with patch('app.telegram.bot._send_message') as mock_send:
                _handle_invite(123, tg.telegram_id)
                mock_send.assert_called_once()
                msg = mock_send.call_args[0][1]
                assert 'register?ref=' in msg
                assert '+100 XP' in msg

            # Cleanup
            db_session.delete(tg)
            db_session.delete(user)
            db_session.commit()


class TestStatsReferralCount:
    """Test that /stats includes referral count."""

    def test_stats_shows_referral_count(self, app, db_session):
        """Stats should show referral count when user has referrals."""
        import uuid
        from app.auth.models import User
        from app.telegram.models import TelegramUser

        with app.app_context():
            suffix = uuid.uuid4().hex[:8]
            referrer = User(username=f'ref_{suffix}', email=f'ref_{suffix}@t.com', active=True)
            referrer.set_password('test')
            db_session.add(referrer)
            db_session.flush()

            referred = User(username=f'rfd_{suffix}', email=f'rfd_{suffix}@t.com', active=True, referred_by_id=referrer.id)
            referred.set_password('test')
            db_session.add(referred)
            db_session.flush()

            tg = TelegramUser(user_id=referrer.id, telegram_id=77770000 + int(suffix[:4], 16), is_active=True)
            db_session.add(tg)
            db_session.commit()

            from app.telegram.bot import _handle_stats
            with patch('app.telegram.bot._send_message') as mock_send, \
                 patch('app.telegram.queries.get_quick_stats', return_value={'streak': 0, 'lessons_completed': 0, 'exercises_done': 0, 'words_in_srs': 0}):
                _handle_stats(123, tg.telegram_id)
                mock_send.assert_called_once()
                msg = mock_send.call_args[0][1]
                assert 'Приглашено друзей: 1' in msg

            # Cleanup
            db_session.delete(tg)
            db_session.delete(referred)
            db_session.delete(referrer)
            db_session.commit()


class TestWeeklyReportInvitePrompt:
    """Test that weekly report includes invite prompt."""

    def test_weekly_report_has_invite_prompt(self, app):
        from datetime import date
        with app.app_context():
            from app.telegram.notifications import format_weekly_report
            report = {
                'week_start': date(2026, 3, 30),
                'week_end': date(2026, 4, 5),
                'active_days': 5,
                'lessons_completed': 10,
                'exercises_done': 50,
                'words_in_srs': 100,
                'streak': 7,
                'prev_lessons': 8,
            }
            result = format_weekly_report(report, 'https://llt-english.com')
            assert '/invite' in result
            assert 'друзьями' in result.lower() or 'приглашения' in result.lower()
