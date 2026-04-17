"""Tests asserting consistent API error response shape across all API modules.

Every error response produced by api_error() must have exactly these keys:
  error   - machine-readable code string
  message - human-readable description
  status  - HTTP status code (integer, mirrors HTTP status)
"""
import pytest


def _assert_error_shape(data: dict, expected_status: int) -> None:
    """Shared helper: verify the three required keys are present and correct."""
    assert 'error' in data, f"Missing 'error' key in {data}"
    assert 'message' in data, f"Missing 'message' key in {data}"
    assert 'status' in data, f"Missing 'status' key in {data}"
    assert isinstance(data['error'], str), "'error' must be a string code"
    assert isinstance(data['message'], str), "'message' must be a string"
    assert data['status'] == expected_status, (
        f"'status' field {data['status']} != HTTP status {expected_status}"
    )


class TestAuthApiErrorShape:
    """Verify api_error() shape for auth endpoints."""

    @pytest.mark.smoke
    def test_invalid_credentials_error_shape(self, client, test_user):
        """Wrong password returns standardized error shape."""
        response = client.post(
            '/api/login',
            json={'username': test_user.username, 'password': 'wrong'}
        )
        assert response.status_code == 401
        _assert_error_shape(response.get_json(), 401)

    def test_missing_fields_error_shape(self, client):
        """Missing fields returns standardized error shape."""
        response = client.post('/api/login', json={'username': 'x'})
        assert response.status_code == 400
        _assert_error_shape(response.get_json(), 400)

    def test_invalid_json_error_shape(self, client):
        """Non-JSON content-type returns standardized error shape."""
        response = client.post(
            '/api/login',
            data='not json',
            content_type='application/json'
        )
        assert response.status_code == 400
        _assert_error_shape(response.get_json(), 400)

    def test_token_refresh_error_shape(self, client):
        """Invalid refresh token returns standardized error shape."""
        response = client.post(
            '/api/refresh',
            headers={'Authorization': 'Bearer bad_token'}
        )
        assert response.status_code == 401
        _assert_error_shape(response.get_json(), 401)


class TestBooksApiErrorShape:
    """Verify api_error() shape for books endpoints."""

    def test_progress_no_data_error_shape(self, authenticated_client):
        """PATCH /api/progress with empty JSON body returns standardized error."""
        # Sending literal null as JSON body — request.get_json() returns None
        response = authenticated_client.patch(
            '/api/progress',
            data=b'null',
            content_type='application/json'
        )
        assert response.status_code == 400
        _assert_error_shape(response.get_json(), 400)

    def test_progress_missing_fields_error_shape(self, authenticated_client):
        """PATCH /api/progress with missing fields returns standardized error."""
        response = authenticated_client.patch(
            '/api/progress',
            json={'chapter_id': 1}
        )
        assert response.status_code == 400
        _assert_error_shape(response.get_json(), 400)

    def test_progress_invalid_offset_error_shape(self, authenticated_client):
        """PATCH /api/progress with out-of-range offset returns standardized error."""
        response = authenticated_client.patch(
            '/api/progress',
            json={'book_id': 1, 'chapter_id': 1, 'offset_pct': 5.0}
        )
        assert response.status_code == 400
        _assert_error_shape(response.get_json(), 400)
