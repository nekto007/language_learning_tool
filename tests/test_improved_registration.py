"""Tests for improved registration flow."""
import pytest


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

    def test_social_proof_counter(self, client):
        """Register page should show learner count."""
        response = client.get('/register')
        html = response.data.decode()
        assert 'ученикам' in html or 'social-proof' in html

    def test_register_preserves_both_params(self, client):
        response = client.get('/register?level=A2&ref=xyz789')
        html = response.data.decode()
        assert 'A2' in html
        assert 'xyz789' in html
