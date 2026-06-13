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
        assert data['status'] == 'ok'
        assert data['db'] == 'ok'

    def test_health_response_contains_version_and_timestamp(self, client):
        response = client.get('/health')
        assert response.status_code == 200
        data = response.get_json()
        assert 'version' in data, "version field missing from health response"
        assert 'timestamp' in data, "timestamp field missing from health response"
        # timestamp must be an ISO-8601 string
        assert isinstance(data['timestamp'], str)
        assert 'T' in data['timestamp'], "timestamp must be ISO-8601 format"

    def test_health_returns_503_when_db_disconnected(self, app):
        with app.test_client() as test_client:
            # Health now pings via a dedicated engine connection (audit E-083),
            # so simulate the failure at engine.connect().
            with patch.object(
                app.extensions['sqlalchemy'].engine,
                'connect',
                side_effect=OperationalError('', '', Exception('connection refused')),
            ):
                response = test_client.get('/health')
                assert response.status_code == 503
                data = response.get_json()
                assert data['status'] == 'error'
                assert data['db'] == 'error'
                # Must NOT leak exception details
                assert 'connection refused' not in str(data)
                # version and timestamp still present even on error
                assert 'version' in data
                assert 'timestamp' in data

    def test_health_no_auth_required(self, client):
        """Health endpoint must work without authentication (for load balancers)."""
        response = client.get('/health')
        # Must not redirect to login
        assert response.status_code not in (301, 302, 401, 403)
        assert response.status_code == 200

    def test_health_no_csrf_required(self, client):
        """Health endpoint must not require CSRF token."""
        response = client.get('/health')
        assert response.status_code == 200

    def test_health_db_timeout_path_does_not_stall(self, app):
        """Simulate statement_timeout firing: health must return 503, not hang."""
        from unittest.mock import MagicMock

        with app.test_client() as test_client:
            def mock_execute(stmt, *args, **kwargs):
                # SET LOCAL succeeds; SELECT 1 raises a timeout-like error.
                if 'SELECT 1' in str(stmt):
                    raise OperationalError('canceling statement due to statement timeout', '', Exception())

            mock_conn = MagicMock()
            mock_conn.__enter__.return_value = mock_conn  # `with engine.connect() as conn`
            mock_conn.execute.side_effect = mock_execute

            with patch.object(
                app.extensions['sqlalchemy'].engine,
                'connect',
                return_value=mock_conn,
            ):
                response = test_client.get('/health')
                assert response.status_code == 503
                data = response.get_json()
                assert data['status'] == 'error'
                assert data['db'] == 'error'
