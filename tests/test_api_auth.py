"""Integration tests for Auth API endpoints"""
import pytest
from datetime import datetime, UTC


class TestAPILogin:
    """Test POST /api/login endpoint"""

    def test_api_login_success(self, client, test_user):
        """Test successful API login with JWT tokens"""
        response = client.post(
            '/api/login',
            json={
                'username': test_user.username,
                'password': 'testpass123'
            }
        )

        assert response.status_code == 200
        data = response.get_json()

        assert data['success'] is True
        assert 'access_token' in data
        assert 'refresh_token' in data
        assert data['token_type'] == 'Bearer'
        assert 'expires_in' in data
        assert 'user' in data
        assert data['user']['username'] == test_user.username
        assert data['user']['id'] == test_user.id

    def test_api_login_invalid_credentials(self, client, test_user):
        """Test login with wrong password"""
        response = client.post(
            '/api/login',
            json={
                'username': test_user.username,
                'password': 'wrongpassword'
            }
        )

        assert response.status_code == 401
        data = response.get_json()

        assert data['error'] == 'invalid_credentials'
        assert data['message'] == 'Invalid credentials'
        assert data['status'] == 401

    def test_api_login_nonexistent_user(self, client):
        """Test login with non-existent username"""
        response = client.post(
            '/api/login',
            json={
                'username': 'nonexistent',
                'password': 'password'
            }
        )

        assert response.status_code == 401
        data = response.get_json()

        assert data['error'] == 'invalid_credentials'

    def test_api_login_missing_username(self, client):
        """Test error when missing username"""
        response = client.post(
            '/api/login',
            json={'password': 'testpass123'}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['error'] == 'missing_fields'
        assert 'Missing username or password' in data['message']

    def test_api_login_missing_password(self, client):
        """Test error when missing password"""
        response = client.post(
            '/api/login',
            json={'username': 'testuser'}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['error'] == 'missing_fields'
        assert 'Missing username or password' in data['message']

    def test_api_login_empty_credentials(self, client):
        """Test error with empty username/password"""
        response = client.post(
            '/api/login',
            json={'username': '', 'password': ''}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert 'error' in data

    def test_api_login_invalid_json(self, client):
        """Test error with invalid JSON"""
        response = client.post(
            '/api/login',
            data='not json',
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['error'] == 'invalid_json'
        assert 'Invalid JSON format' in data['message']

    def test_api_login_not_json_content_type(self, client, test_user):
        """Test error when not sending JSON content type"""
        response = client.post(
            '/api/login',
            data={'username': 'testuser', 'password': 'testpass123'}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['error'] == 'invalid_json'
        assert 'Invalid JSON format' in data['message']

    def test_api_login_updates_last_login(self, client, test_user, db_session):
        """Test that successful login updates last_login timestamp"""
        from app.auth.models import User

        # Get initial last_login
        initial_last_login = test_user.last_login

        response = client.post(
            '/api/login',
            json={
                'username': test_user.username,
                'password': 'testpass123'
            }
        )

        assert response.status_code == 200

        # Refresh user from DB
        db_session.refresh(test_user)

        # last_login should be updated
        assert test_user.last_login is not None
        if initial_last_login:
            assert test_user.last_login > initial_last_login


class TestAPIRefresh:
    """Test POST /api/refresh endpoint"""

    def test_refresh_token_success(self, client, test_user):
        """Test successfully refreshing access token"""
        # First login to get tokens
        login_response = client.post(
            '/api/login',
            json={
                'username': test_user.username,
                'password': 'testpass123'
            }
        )

        assert login_response.status_code == 200
        login_data = login_response.get_json()
        refresh_token = login_data['refresh_token']

        # Use refresh token to get new access token
        refresh_response = client.post(
            '/api/refresh',
            headers={'Authorization': f'Bearer {refresh_token}'}
        )

        assert refresh_response.status_code == 200
        refresh_data = refresh_response.get_json()

        assert refresh_data['success'] is True
        assert 'access_token' in refresh_data
        assert refresh_data['token_type'] == 'Bearer'
        assert 'expires_in' in refresh_data

    def test_refresh_without_token(self, client):
        """Test refresh without providing token"""
        response = client.post('/api/refresh')

        assert response.status_code == 401

    def test_refresh_with_invalid_token(self, client):
        """Test refresh with invalid token"""
        response = client.post(
            '/api/refresh',
            headers={'Authorization': 'Bearer invalid_token_here'}
        )

        assert response.status_code == 401  # Returns 401 for invalid tokens

    def test_refresh_with_access_token_instead_of_refresh(self, client, test_user):
        """Test that using access token for refresh fails"""
        # Login to get tokens
        login_response = client.post(
            '/api/login',
            json={
                'username': test_user.username,
                'password': 'testpass123'
            }
        )

        login_data = login_response.get_json()
        access_token = login_data['access_token']

        # Try to use access token for refresh (should fail)
        refresh_response = client.post(
            '/api/refresh',
            headers={'Authorization': f'Bearer {access_token}'}
        )

        # Should fail because access token is not a refresh token
        assert refresh_response.status_code == 401


class TestAPIAuthRequired:
    """Test unified @api_auth_required decorator (JWT + session fallback)"""

    def test_endpoint_accepts_jwt_token(self, client, test_user):
        """Endpoints accept JWT Bearer tokens"""
        login_response = client.post(
            '/api/login',
            json={
                'username': test_user.username,
                'password': 'testpass123'
            }
        )

        login_data = login_response.get_json()
        access_token = login_data['access_token']

        response = client.get(
            '/api/words',
            headers={'Authorization': f'Bearer {access_token}'}
        )

        assert response.status_code == 200

    def test_endpoint_accepts_session_cookie(self, authenticated_client):
        """Endpoints accept session cookie auth"""
        response = authenticated_client.get('/api/words')
        assert response.status_code == 200

    def test_endpoint_rejects_unauthenticated(self, client):
        """Endpoints reject unauthenticated requests"""
        response = client.get('/api/words')

        assert response.status_code == 401
        data = response.get_json()

        assert data['success'] is False
        assert 'Authentication required' in data['error']

    def test_endpoint_rejects_invalid_jwt(self, client):
        """Endpoints reject invalid JWT tokens"""
        response = client.get(
            '/api/words',
            headers={'Authorization': 'Bearer invalid_token_here'}
        )

        assert response.status_code == 401
        data = response.get_json()
        assert data['success'] is False

    def test_jwt_preferred_over_session(self, client, test_user):
        """JWT auth works even without a session"""
        login_response = client.post(
            '/api/login',
            json={
                'username': test_user.username,
                'password': 'testpass123'
            }
        )
        access_token = login_response.get_json()['access_token']

        response = client.get(
            '/api/words',
            headers={'Authorization': f'Bearer {access_token}'}
        )
        assert response.status_code == 200
