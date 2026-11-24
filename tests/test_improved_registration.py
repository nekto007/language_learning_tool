"""Tests for improved registration flow."""
from bs4 import BeautifulSoup
from flask.testing import FlaskClient

from app.auth.models import User


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
