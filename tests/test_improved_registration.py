"""Tests for improved registration flow."""
from collections.abc import Iterator

import pytest
from bs4 import BeautifulSoup
from flask.testing import FlaskClient
from flask_babel import force_locale

from app.auth.models import User


@pytest.fixture
def russian_client(client: FlaskClient) -> Iterator[FlaskClient]:
    with force_locale('ru'):
        yield client


class TestRegistrationPage:
    """Test registration page improvements."""

    def test_register_returns_200(self, client):
        response = client.get('/register')
        assert response.status_code == 200

    def test_register_with_level_param(self, client):
        response = client.get('/register?level=B1')
        html = response.data.decode()
        assert response.status_code == 200
        assert 'B1' in html  # level preserved in form action

    def test_register_with_ref_param(self, client):
        response = client.get('/register?ref=abc123')
        html = response.data.decode()
        assert response.status_code == 200
        assert 'abc123' in html  # ref preserved as hidden input

    def test_social_proof_counter(self, client: FlaskClient, test_user: User) -> None:
        page = BeautifulSoup(client.get('/register').data, 'html.parser')
        counter = page.select_one('.auth-card__social-proof')
        assert counter is not None
        assert str(User.query.filter_by(active=True).count()) in counter.get_text()

    def test_referral_signup_omits_missing_learner_count(self, client: FlaskClient) -> None:
        page = BeautifulSoup(client.get('/register?ref=abc123').data, 'html.parser')
        assert page.select_one('.auth-card__social-proof') is None
        assert 'social-proof' not in page.get_text()

    def test_register_preserves_both_params(self, client):
        response = client.get('/register?level=A2&ref=xyz789')
        html = response.data.decode()
        assert 'A2' in html
        assert 'xyz789' in html

    def test_registration_focuses_first_error_without_script(self, russian_client: FlaskClient, test_user: User) -> None:
        initial = BeautifulSoup(russian_client.get('/register').data, 'html.parser')
        assert not initial.select('form [autofocus]')
        response = russian_client.post('/register', data={
            'username': 'returning_reader', 'email': test_user.email,
            'password': 'Rain9!Garden', 'password2': 'mismatch',
        })
        page = BeautifulSoup(response.data, 'html.parser')
        assert [field['name'] for field in page.select('form [autofocus]')] == ['email']
        assert page.select_one('#email')['value'] == test_user.email
        assert page.select_one('#email')['aria-describedby'] == 'email-errors'
        assert 'Эта почта уже зарегистрирована.' in page.select_one('#email-errors').get_text()
        assert page.select_one('#password2')['aria-invalid'] == 'true'

    def test_login_keyboard_focus_and_password_manager_fields(self, russian_client: FlaskClient) -> None:
        initial = BeautifulSoup(russian_client.get('/login').data, 'html.parser')
        assert not initial.select('form [autofocus]')
        assert initial.select_one('label[for=username_or_email]').get_text(strip=True) == 'Имя пользователя или электронная почта'
        assert initial.select_one('#username_or_email')['autocomplete'] == 'username'
        assert initial.select_one('#password')['autocomplete'] == 'current-password'
        missing = BeautifulSoup(russian_client.post('/login', data={}).data, 'html.parser')
        assert [field['name'] for field in missing.select('form [autofocus]')] == ['username_or_email']
        assert missing.select_one('#username_or_email')['aria-describedby'] == 'login-name-errors'
        response = russian_client.post('/login', data={'username_or_email': 'absent_reader', 'password': 'incorrect'})
        assert response.status_code == 401
        failed = BeautifulSoup(response.data, 'html.parser')
        assert [field['name'] for field in failed.select('form [autofocus]')] == ['password']
        assert failed.select_one('#username_or_email')['value'] == 'absent_reader'
        assert failed.select_one('#password')['aria-describedby'] == 'public-flashes'
        assert 'Неверное имя пользователя или пароль' in failed.select_one('#public-flashes').get_text()
