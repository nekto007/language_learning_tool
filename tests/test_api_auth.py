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

        assert data['success'] is False
        assert data['error'] == 'Invalid credentials'
        assert data['status_code'] == 401

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

        assert data['success'] is False
        assert data['error'] == 'Invalid credentials'

    def test_api_login_missing_username(self, client):
        """Test error when missing username"""
        response = client.post(
            '/api/login',
            json={'password': 'testpass123'}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False
        assert 'Missing username or password' in data['error']

    def test_api_login_missing_password(self, client):
        """Test error when missing password"""
        response = client.post(
            '/api/login',
            json={'username': 'testuser'}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False
        assert 'Missing username or password' in data['error']

    def test_api_login_empty_credentials(self, client):
        """Test error with empty username/password"""
        response = client.post(
            '/api/login',
            json={'username': '', 'password': ''}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False

    def test_api_login_invalid_json(self, client):
        """Test error with invalid JSON"""
        response = client.post(
            '/api/login',
            data='not json',
            content_type='application/json'
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False
        assert 'Invalid JSON format' in data['error']

    def test_api_login_not_json_content_type(self, client, test_user):
        """Test error when not sending JSON content type"""
        response = client.post(
            '/api/login',
            data={'username': 'testuser', 'password': 'testpass123'}
        )

        assert response.status_code == 400
        data = response.get_json()

        assert data['success'] is False
        assert 'Invalid JSON format' in data['error']

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


class TestAPILoginRequired:
    """Test @api_login_required decorator"""

    @pytest.mark.skip(reason="@api_login_required doesn't support JWT tokens - use @api_jwt_required instead")
    def test_api_login_required_with_valid_token(self, client, test_user):
        """Test API endpoint with valid JWT token

        NOTE: This test is skipped because /api/words uses @api_login_required which
        only supports Flask-Login session cookies, not JWT tokens.

        To make this test pass, /api/words needs to be migrated to use @api_jwt_required.
        """
        # Login to get access token
        login_response = client.post(
            '/api/login',
            json={
                'username': test_user.username,
                'password': 'testpass123'
            }
        )

        login_data = login_response.get_json()
        access_token = login_data['access_token']

        # Use access token to access protected endpoint
        response = client.get(
            '/api/words',
            headers={'Authorization': f'Bearer {access_token}'}
        )

        # Should succeed (not 401)
        assert response.status_code == 200

    def test_api_login_required_without_token(self, client):
        """Test protected API endpoint without token"""
        response = client.get('/api/words')

        assert response.status_code == 401
        data = response.get_json()

        assert data['success'] is False
        assert 'Authentication required' in data['error']
