"""Tests for the /health endpoint."""
import pytest
from unittest.mock import patch
from sqlalchemy.exc import OperationalError


class TestHealthCheck:
    """Test health check endpoint returns correct status."""

    @pytest.mark.smoke
    def test_health_returns_200_when_db_connected(self, client):
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'
        assert data['database'] == 'connected'

    def test_health_returns_503_when_db_disconnected(self, app):
        with app.test_client() as client:
            with patch.object(
                app.extensions['sqlalchemy'].session,
                'execute',
                side_effect=OperationalError('', '', Exception('connection refused')),
            ):
                response = client.get('/health')
                assert response.status_code == 503
                data = response.get_json()
                assert data['status'] == 'unhealthy'
                assert data['db'] == 'error'
                # Must NOT leak exception details
                assert 'connection refused' not in str(data)

    def test_health_no_auth_required(self, client):
        """Health endpoint must work without authentication."""
        response = client.get('/health')
        assert response.status_code == 200
        assert response.status_code != 302

    def test_health_no_csrf_required(self, client):
        """Health endpoint must not require CSRF token."""
        response = client.get('/health')
        assert response.status_code == 200
