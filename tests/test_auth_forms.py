"""
Tests for auth forms
Тесты форм аутентификации
"""
import pytest
from app.auth.forms import LoginForm, RegistrationForm, RequestResetForm, ResetPasswordForm
from app.auth.models import User


class TestRegistrationForm:
    """Тесты формы регистрации"""

    def test_validate_username_already_exists(self, app, db_session):
        """Тест валидации существующего username"""
        import uuid
        with app.app_context():
            # Создаем пользователя
            unique_id = uuid.uuid4().hex[:8]
            user = User(username=f'testuser_{unique_id}', email=f'test_{unique_id}@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            # Пытаемся зарегистрировать с тем же username
            form = RegistrationForm(
                username=f'testuser_{unique_id}',
                email='another@example.com',
                password='ValidPass123!',
                password2='ValidPass123!'
            )

            # Валидация должна провалиться
            assert not form.validate()
            assert 'username' in form.errors

    def test_validate_email_already_exists(self, app, db_session):
        """Тест валидации существующего email"""
        import uuid
        with app.app_context():
            # Создаем пользователя
            unique_id = uuid.uuid4().hex[:8]
            user = User(username=f'testuser_{unique_id}', email=f'test_{unique_id}@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            # Пытаемся зарегистрировать с тем же email
            form = RegistrationForm(
                username='anotheruser',
                email=f'test_{unique_id}@example.com',
                password='ValidPass123!',
                password2='ValidPass123!'
            )

            # Валидация должна провалиться
            assert not form.validate()
            assert 'email' in form.errors

    def test_validate_weak_password(self, app, db_session):
        """Тест валидации слабого пароля"""
        with app.app_context():
            # Пытаемся зарегистрировать со слабым паролем
            form = RegistrationForm(
                username='newuser',
                email='new@example.com',
                password='weak',
                password2='weak'
            )

            # Валидация должна провалиться из-за слабого пароля
            assert not form.validate()
            # Может быть ошибка в password или length validator
            assert 'password' in form.errors or 'password2' in form.errors

    def test_validate_password_mismatch(self, app, db_session):
        """Тест валидации несовпадающих паролей"""
        with app.app_context():
            form = RegistrationForm(
                username='newuser',
                email='new@example.com',
                password='ValidPass123!',
                password2='DifferentPass123!'
            )

            # Валидация должна провалиться
            assert not form.validate()
            assert 'password2' in form.errors



class TestRequestResetForm:
    """Тесты формы запроса сброса пароля"""

    def test_validate_unknown_email_passes_form(self, app, db_session):
        """RequestResetForm must NOT reject unknown emails at form-validation time.

        Doing so would allow user enumeration.  The route handles unknown
        addresses by showing the same success message as for known ones.
        """
        with app.app_context():
            form = RequestResetForm(email='nonexistent@example.com')
            # Form should pass — no DB check at form level
            assert form.validate(), (
                "RequestResetForm must not reject unknown emails (would leak user existence). "
                f"Form errors: {form.errors}"
            )

    def test_validate_email_exists(self, app, db_session):
        """Тест валидации существующего email"""
        import uuid
        with app.app_context():
            # Создаем пользователя
            unique_id = uuid.uuid4().hex[:8]
            user = User(username=f'testuser_{unique_id}', email=f'test_{unique_id}@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            # Запрашиваем сброс для существующего email
            form = RequestResetForm(
                email=f'test_{unique_id}@example.com'
            )

            # Валидация должна пройти
            assert form.validate()

    def test_validate_email_too_long_rejected(self, app):
        """Email > 254 chars must be rejected by the Length validator."""
        with app.app_context():
            long_email = 'a' * 243 + '@example.com'  # 255 chars
            assert len(long_email) == 255
            form = RequestResetForm(email=long_email)
            assert not form.validate()
            assert 'email' in form.errors


class TestResetPasswordForm:
    """Тесты формы сброса пароля"""

    def test_validate_weak_password(self, app, db_session):
        """Тест валидации слабого пароля"""
        with app.app_context():
            # Пытаемся установить слабый пароль
            form = ResetPasswordForm(
                password='weak',
                password2='weak'
            )

            # Валидация должна провалиться
            assert not form.validate()
            assert 'password' in form.errors or 'password2' in form.errors

    def test_validate_password_mismatch(self, app, db_session):
        """Тест валидации несовпадающих паролей"""
        with app.app_context():
            form = ResetPasswordForm(
                password='ValidPass123!',
                password2='DifferentPass123!'
            )

            # Валидация должна провалиться
            assert not form.validate()
            assert 'password2' in form.errors



class TestLoginForm:
    """Тесты формы входа"""

    def test_login_form_creation(self, app):
        """Тест создания формы входа"""
        with app.app_context():
            form = LoginForm(
                username_or_email='testuser',
                password='password123',
                remember_me=True
            )

            assert form.username_or_email.data == 'testuser'
            assert form.password.data == 'password123'
            assert form.remember_me.data is True

    def test_login_rejects_oversized_username_or_email(self, app):
        """username_or_email > 254 chars must fail form validation."""
        with app.app_context():
            long_input = 'a' * 255
            form = LoginForm(username_or_email=long_input, password='pass')
            # form.validate() calls all validators; Length(max=254) should fail
            form.validate()
            assert 'username_or_email' in form.errors, (
                "LoginForm must reject username_or_email > 254 chars"
            )

    def test_login_rejects_oversized_password(self, app):
        """password > 128 chars must fail form validation."""
        with app.app_context():
            long_pass = 'A1!' + 'x' * 130
            form = LoginForm(username_or_email='user', password=long_pass)
            form.validate()
            assert 'password' in form.errors, (
                "LoginForm must reject password > 128 chars"
            )

    def test_login_accepts_max_length_inputs(self, app):
        """username_or_email at 254 chars and password at 128 chars must pass length validators."""
        with app.app_context():
            exactly_254 = 'a' * 242 + '@example.com'
            exactly_128 = 'Aa1!' * 32  # 128 chars
            assert len(exactly_254) == 254
            assert len(exactly_128) == 128
            form = LoginForm(username_or_email=exactly_254, password=exactly_128)
            form.validate()
            # Only DataRequired/Length errors expected — not length overflow
            length_err_user = any('254' in e or 'long' in e.lower() for e in form.errors.get('username_or_email', []))
            length_err_pass = any('128' in e or 'long' in e.lower() for e in form.errors.get('password', []))
            assert not length_err_user, "username_or_email at exactly 254 chars should not fail Length(max=254)"
            assert not length_err_pass, "password at exactly 128 chars should not fail Length(max=128)"
