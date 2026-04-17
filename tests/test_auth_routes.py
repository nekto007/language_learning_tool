"""
Integration tests for app/auth/routes.py

Tests all auth endpoints:
- GET/POST /login
- GET/POST /register
- GET /logout
- GET/POST /reset_password
- GET/POST /reset_password/<token>
- GET/POST /profile
- GET/POST /change-password
"""
import pytest
import uuid
from unittest.mock import patch, MagicMock

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.auth.models import User
from app.utils.db import db


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    @pytest.mark.smoke
    def test_login_page_renders(self, client):
        r = client.get('/login')
        assert r.status_code == 200

    @pytest.mark.smoke
    def test_login_with_username(self, client, test_user):
        r = client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302

    def test_login_with_email(self, client, test_user):
        r = client.post('/login', data={
            'username_or_email': test_user.email,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302

    def test_login_wrong_password(self, client, test_user):
        r = client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'wrongpass',
        }, follow_redirects=False)
        assert r.status_code == 401

    def test_login_nonexistent_user(self, client):
        r = client.post('/login', data={
            'username_or_email': 'nonexistent_user_xyz',
            'password': 'whatever',
        }, follow_redirects=False)
        assert r.status_code == 401

    def test_failed_login_emits_warning_log(self, client, test_user, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger='app.auth.routes'):
            client.post('/login', data={
                'username_or_email': test_user.username,
                'password': 'wrongpassword',
            }, follow_redirects=False)
        assert 'failed login attempt' in caplog.text
        assert test_user.username in caplog.text

    def test_failed_login_nonexistent_user_emits_warning_log(self, client, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger='app.auth.routes'):
            client.post('/login', data={
                'username_or_email': 'ghost_user_xyz',
                'password': 'whatever',
            }, follow_redirects=False)
        assert 'failed login attempt' in caplog.text
        assert 'ghost_user_xyz' in caplog.text

    def test_login_inactive_user(self, client, db_session, test_user):
        test_user.active = False
        db_session.commit()
        r = client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=True)
        assert r.status_code == 200
        assert 'неактивна' in r.data.decode().lower() or 'inactive' in r.data.decode().lower()

    def test_login_redirect_next(self, client, test_user):
        r = client.post('/login?next=/curriculum/api/levels', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        assert '/curriculum/api/levels' in r.headers.get('Location', '')

    def test_login_already_authenticated(self, authenticated_client):
        r = authenticated_client.get('/login', follow_redirects=False)
        assert r.status_code == 302

    def test_login_updates_last_login(self, client, db_session, test_user):
        old_login = test_user.last_login
        client.post('/login', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        db_session.refresh(test_user)
        assert test_user.last_login is not None
        if old_login:
            assert test_user.last_login >= old_login


# ---------------------------------------------------------------------------
# Safe redirect
# ---------------------------------------------------------------------------

class TestSafeRedirect:
    def test_blocks_external_url(self, client, test_user):
        r = client.post('/login?next=http://evil.com/steal', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'evil.com' not in loc

    def test_blocks_javascript_scheme(self, client, test_user):
        r = client.post('/login?next=javascript:alert(1)', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'javascript' not in loc

    def test_blocks_https_external_url(self, client, test_user):
        """login with next=https://evil.com must redirect to home, not evil.com."""
        r = client.post('/login?next=https://evil.com', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert 'evil.com' not in loc

    def test_allows_safe_internal_path(self, client, test_user):
        """login with next=/study/ must redirect to /study/."""
        r = client.post('/login?next=/study/', data={
            'username_or_email': test_user.username,
            'password': 'testpass123',
        }, follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers.get('Location', '')
        assert '/study/' in loc


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

class TestRegister:
    @pytest.mark.smoke
    def test_register_page_renders(self, client):
        r = client.get('/register')
        assert r.status_code == 200

    def test_register_already_authenticated(self, authenticated_client):
        r = authenticated_client.get('/register', follow_redirects=False)
        assert r.status_code == 302

    @patch('app.auth.routes.email_sender')
    @pytest.mark.smoke
    def test_register_success(self, mock_email, client, db_session):
        mock_email.send_email.return_value = True
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'newuser_{unique}',
            'email': f'newuser_{unique}@example.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302

    @patch('app.auth.routes.email_sender')
    def test_register_auto_login_and_redirect_to_onboarding(self, mock_email, client, db_session):
        """After registration, user should be logged in and redirected to onboarding."""
        mock_email.send_email.return_value = True
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'newuser_{unique}',
            'email': f'newuser_{unique}@example.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302
        location = r.headers.get('Location', '')
        assert '/onboarding' in location

        # Verify user is logged in: accessing a login-required page should NOT
        # redirect to /login. It may return 200 or redirect to onboarding, but not login.
        r2 = client.get('/dashboard', follow_redirects=False)
        assert r2.status_code in (200, 302)
        if r2.status_code == 302:
            assert '/login' not in r2.headers.get('Location', '')

    @patch('app.auth.routes.email_sender')
    def test_register_sends_welcome_email(self, mock_email, client, db_session):
        """Registration should send a welcome email."""
        mock_email.send_email.return_value = True
        unique = uuid.uuid4().hex[:8]
        email = f'newuser_{unique}@example.com'
        client.post('/register', data={
            'username': f'newuser_{unique}',
            'email': email,
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        mock_email.send_email.assert_called_once()
        call_kwargs = mock_email.send_email.call_args
        assert call_kwargs[1]['to_email'] == email
        assert call_kwargs[1]['template_name'] == 'welcome'

    @patch('app.auth.routes.email_sender')
    def test_register_succeeds_even_if_email_fails(self, mock_email, client, db_session):
        """Registration should succeed even if welcome email sending fails."""
        mock_email.send_email.side_effect = OSError("SMTP connection refused")
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'newuser_{unique}',
            'email': f'newuser_{unique}@example.com',
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302  # Still redirects to dashboard

    def test_register_duplicate_username(self, client, test_user):
        r = client.post('/register', data={
            'username': test_user.username,
            'email': 'different@example.com',
            'password': 'StrongPass123!@#',
            'password2': 'StrongPass123!@#',
        }, follow_redirects=True)
        assert r.status_code == 200  # Stays on form with error

    def test_register_duplicate_email(self, client, test_user):
        r = client.post('/register', data={
            'username': f'unique_{uuid.uuid4().hex[:8]}',
            'email': test_user.email,
            'password': 'StrongPass123!@#',
            'password2': 'StrongPass123!@#',
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_register_password_mismatch(self, client):
        unique = uuid.uuid4().hex[:8]
        r = client.post('/register', data={
            'username': f'user_{unique}',
            'email': f'user_{unique}@example.com',
            'password': 'StrongPass123!@#',
            'password2': 'DifferentPass!@#',
        }, follow_redirects=True)
        assert r.status_code == 200  # Form re-rendered with error


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    @pytest.mark.smoke
    def test_logout_redirects(self, authenticated_client):
        r = authenticated_client.get('/logout', follow_redirects=False)
        assert r.status_code == 302

    def test_logout_unauthenticated(self, client):
        r = client.get('/logout')
        assert r.status_code in [302, 401]


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class TestProfile:
    def test_profile_requires_login(self, client):
        r = client.get('/profile')
        assert r.status_code in [302, 401]


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

class TestChangePassword:
    def test_requires_login(self, client):
        r = client.get('/change-password')
        assert r.status_code in [302, 401]


# ---------------------------------------------------------------------------
# Password reset request
# ---------------------------------------------------------------------------

class TestPasswordResetRequest:
    def test_page_renders(self, client):
        r = client.get('/reset_password')
        assert r.status_code == 200

    def test_already_authenticated(self, authenticated_client):
        r = authenticated_client.get('/reset_password', follow_redirects=False)
        assert r.status_code == 302

    @patch('app.auth.routes.email_sender')
    def test_valid_email(self, mock_email, client, test_user):
        mock_email.send_email.return_value = True
        r = client.post('/reset_password', data={
            'email': test_user.email,
        }, follow_redirects=False)
        assert r.status_code == 302

    @patch('app.auth.routes.email_sender')
    def test_unknown_email_still_redirects(self, mock_email, client):
        """Should not reveal whether email exists."""
        r = client.post('/reset_password', data={
            'email': 'nonexistent@example.com',
        }, follow_redirects=True)
        assert r.status_code == 200

    @patch('app.auth.routes.email_sender')
    def test_email_send_failure(self, mock_email, client, test_user):
        mock_email.send_email.return_value = False
        r = client.post('/reset_password', data={
            'email': test_user.email,
        }, follow_redirects=True)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Password reset with token
# ---------------------------------------------------------------------------

class TestPasswordResetWithToken:
    def test_invalid_token(self, client):
        r = client.get('/reset_password/invalidtoken123')
        assert r.status_code == 302

    def test_valid_token_renders_form(self, client, test_user):
        from app.auth.routes import get_reset_token
        token = get_reset_token(test_user.id)
        r = client.get(f'/reset_password/{token}')
        assert r.status_code == 200

    def test_already_authenticated(self, authenticated_client):
        r = authenticated_client.get('/reset_password/sometoken', follow_redirects=False)
        assert r.status_code == 302


# ---------------------------------------------------------------------------
# Token generation / verification helpers
# ---------------------------------------------------------------------------

class TestTokenHelpers:
    def test_get_reset_token(self, app, test_user):
        from app.auth.routes import get_reset_token
        with app.app_context():
            token = get_reset_token(test_user.id)
            assert isinstance(token, str) and len(token) > 0

    def test_verify_reset_token(self, app, test_user):
        from app.auth.routes import get_reset_token, verify_reset_token
        with app.app_context():
            token = get_reset_token(test_user.id)
            uid = verify_reset_token(token)
            assert uid == test_user.id

    def test_verify_invalid_token(self, app):
        from app.auth.routes import verify_reset_token
        with app.app_context():
            assert verify_reset_token('totally_invalid') is None

    def test_token_stored_in_db(self, app, db_session, test_user):
        """get_reset_token must store a hash in PasswordResetToken table."""
        from app.auth.routes import get_reset_token, _hash_token
        from app.auth.models import PasswordResetToken
        with app.app_context():
            token = get_reset_token(test_user.id)
            token_hash = _hash_token(token)
            record = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
            assert record is not None
            assert record.user_id == test_user.id
            assert record.used_at is None

    def test_token_single_use_rejected_after_use(self, app, db_session, test_user):
        """verify_reset_token must return None after token is marked as used."""
        from datetime import datetime, timezone
        from app.auth.routes import get_reset_token, verify_reset_token, _hash_token
        from app.auth.models import PasswordResetToken
        with app.app_context():
            token = get_reset_token(test_user.id)
            # Verify once — should succeed
            uid = verify_reset_token(token)
            assert uid == test_user.id

            # Mark token as used
            token_hash = _hash_token(token)
            record = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
            record.used_at = datetime.now(timezone.utc)
            db_session.commit()

            # Verify again — must be rejected
            uid2 = verify_reset_token(token)
            assert uid2 is None


class TestPasswordResetSingleUse:
    """Integration tests: using the same reset token twice must fail."""

    def test_second_use_of_token_rejected(self, client, db_session, test_user):
        """GET /reset_password/<token> must redirect away if token already used."""
        from app.auth.routes import get_reset_token, _hash_token
        from app.auth.models import PasswordResetToken
        from datetime import datetime, timezone

        with client.application.app_context():
            token = get_reset_token(test_user.id)

            # Simulate first use: mark token as used
            token_hash = _hash_token(token)
            record = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
            record.used_at = datetime.now(timezone.utc)
            db_session.commit()

        # Second GET with the same token must redirect (token now invalid)
        r = client.get(f'/reset_password/{token}')
        assert r.status_code == 302

    @patch('app.auth.routes.email_sender')
    def test_successful_reset_marks_token_used(self, mock_email, client, db_session, test_user):
        """After a successful password reset, the token must be marked as used."""
        from app.auth.routes import get_reset_token, _hash_token
        from app.auth.models import PasswordResetToken

        mock_email.send_email.return_value = True

        with client.application.app_context():
            token = get_reset_token(test_user.id)

        # Submit the reset form (password must pass strength check: no sequences like 123)
        r = client.post(f'/reset_password/{token}', data={
            'password': 'Xk9$mP2vL!qw',
            'password2': 'Xk9$mP2vL!qw',
        }, follow_redirects=False)
        assert r.status_code == 302

        # Token record must now have used_at set
        with client.application.app_context():
            token_hash = _hash_token(token)
            record = PasswordResetToken.query.filter_by(token_hash=token_hash).first()
            assert record is not None
            assert record.used_at is not None



# ---------------------------------------------------------------------------
# Exception handling — auth flow must fail-closed
# ---------------------------------------------------------------------------

class TestAuthExceptionHandling:
    @patch('app.auth.routes.email_sender')
    def test_db_error_during_registration_shows_error(self, mock_email, client, db_session):
        """DB error during registration must not silently log user in."""
        mock_email.send_email.return_value = True
        unique = uuid.uuid4().hex[:8]
        with patch('app.auth.routes.db.session.commit', side_effect=SQLAlchemyError("DB down")):
            r = client.post('/register', data={
                'username': f'newuser_{unique}',
                'email': f'newuser_{unique}@example.com',
                'password': 'Xk9$mP2vL!qw',
                'password2': 'Xk9$mP2vL!qw',
            }, follow_redirects=True)
            assert r.status_code == 200
            page = r.data.decode()
            assert 'не удалась' in page.lower() or 'danger' in page.lower()

    def test_db_error_during_profile_update_rolls_back(self, authenticated_client, db_session):
        """Profile update DB error must rollback and show error flash."""
        original_commit = db.session.commit
        call_count = [0]

        def commit_that_fails_second_time():
            call_count[0] += 1
            if call_count[0] > 1:
                raise SQLAlchemyError("DB error")
            return original_commit()

        with patch.object(db.session, 'commit', side_effect=commit_that_fails_second_time):
            r = authenticated_client.post('/profile', data={
                'section': 'settings',
                'timezone': 'UTC',
            }, follow_redirects=True)
            assert r.status_code == 200

    def test_db_error_during_password_change_logs_exception(self, authenticated_client, test_user, caplog):
        """Password change DB error must log exception and rollback."""
        import logging
        original_commit = db.session.commit
        call_count = [0]

        def commit_that_fails_second_time():
            call_count[0] += 1
            if call_count[0] > 1:
                raise SQLAlchemyError("DB error")
            return original_commit()

        with caplog.at_level(logging.ERROR, logger='app.auth.routes'):
            with patch.object(db.session, 'commit', side_effect=commit_that_fails_second_time):
                try:
                    authenticated_client.post('/change-password', data={
                        'current_password': 'testpass123',
                        'new_password': 'NewPass123!@#',
                        'confirm_password': 'NewPass123!@#',
                    })
                except Exception:
                    pass
            assert 'Failed to change password' in caplog.text


# ---------------------------------------------------------------------------
# Duplicate email registration — DB-level IntegrityError handling (task 41)
# ---------------------------------------------------------------------------

class TestDuplicateEmailRegistration:
    """Tests for race-condition duplicate email handling at the DB constraint level."""

    def _make_integrity_error(self, msg: str) -> IntegrityError:
        """Helper: build an IntegrityError whose orig.lower() contains `msg`."""
        orig = Exception(msg)
        return IntegrityError("INSERT INTO users ...", {}, orig)

    @pytest.mark.smoke
    def test_duplicate_email_db_constraint_returns_400(self, client, db_session):
        """When DB-level IntegrityError fires for email, route returns 400 with duplicate email message."""
        unique = uuid.uuid4().hex[:8]
        err = self._make_integrity_error(f"UNIQUE constraint failed: users.email")
        with patch('app.auth.routes.db.session.commit', side_effect=err):
            r = client.post('/register', data={
                'username': f'newuser_{unique}',
                'email': f'newuser_{unique}@example.com',
                'password': 'Xk9$mP2vL!qw',
                'password2': 'Xk9$mP2vL!qw',
            }, follow_redirects=True)
        assert r.status_code == 400
        assert 'уже зарегистрирован' in r.data.decode()

    def test_duplicate_email_db_session_clean_after_error(self, client, db_session):
        """DB session must be clean (rollback called) after duplicate email IntegrityError."""
        unique = uuid.uuid4().hex[:8]
        err = self._make_integrity_error("UNIQUE constraint failed: users.email")
        rollback_called = []

        original_rollback = db.session.rollback

        def tracking_rollback():
            rollback_called.append(True)
            return original_rollback()

        with patch('app.auth.routes.db.session.commit', side_effect=err):
            with patch.object(db.session, 'rollback', side_effect=tracking_rollback):
                client.post('/register', data={
                    'username': f'newuser_{unique}',
                    'email': f'newuser_{unique}@example.com',
                    'password': 'Xk9$mP2vL!qw',
                    'password2': 'Xk9$mP2vL!qw',
                }, follow_redirects=True)
        assert rollback_called, "db.session.rollback() must be called on duplicate email error"

    def test_non_email_integrity_error_shows_generic_message(self, client, db_session):
        """IntegrityError unrelated to email shows generic error, not duplicate email message."""
        unique = uuid.uuid4().hex[:8]
        err = self._make_integrity_error("UNIQUE constraint failed: users.username")
        with patch('app.auth.routes.db.session.commit', side_effect=err):
            r = client.post('/register', data={
                'username': f'newuser_{unique}',
                'email': f'newuser_{unique}@example.com',
                'password': 'Xk9$mP2vL!qw',
                'password2': 'Xk9$mP2vL!qw',
            }, follow_redirects=True)
        assert r.status_code == 200
        assert 'уже зарегистрирован' not in r.data.decode()
