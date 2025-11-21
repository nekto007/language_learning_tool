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
        with app.app_context():
            # Создаем пользователя
            user = User(username='testuser', email='test@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            # Пытаемся зарегистрировать с тем же username
            form = RegistrationForm(
                username='testuser',
                email='another@example.com',
                password='ValidPass123!',
                password2='ValidPass123!'
            )

            # Валидация должна провалиться
            assert not form.validate()
            assert 'username' in form.errors

    def test_validate_email_already_exists(self, app, db_session):
        """Тест валидации существующего email"""
        with app.app_context():
            # Создаем пользователя
            user = User(username='testuser', email='test@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            # Пытаемся зарегистрировать с тем же email
            form = RegistrationForm(
                username='anotheruser',
                email='test@example.com',
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

    def test_validate_email_not_exists(self, app, db_session):
        """Тест валидации несуществующего email"""
        with app.app_context():
            # Пытаемся сбросить пароль для несуществующего email
            form = RequestResetForm(
                email='nonexistent@example.com'
            )

            # Валидация должна провалиться
            assert not form.validate()
            assert 'email' in form.errors

    def test_validate_email_exists(self, app, db_session):
        """Тест валидации существующего email"""
        with app.app_context():
            # Создаем пользователя
            user = User(username='testuser', email='test@example.com')
            user.set_password('password123')
            db_session.add(user)
            db_session.commit()

            # Запрашиваем сброс для существующего email
            form = RequestResetForm(
                email='test@example.com'
            )

            # Валидация должна пройти
            assert form.validate()


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
