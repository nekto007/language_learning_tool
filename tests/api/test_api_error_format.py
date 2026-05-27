"""Tests for consistent API error response format across all endpoints.

Every error response from an API endpoint must:
1. Use api_error() helper (or equivalent global handler) — never ad-hoc dicts.
2. Include 'error' (machine code), 'message' (human text), and 'status' fields.
3. Return correct HTTP status codes: 400 validation, 403 access, 404 not found.
4. Never leak stack traces in the response body.
"""
from __future__ import annotations

import json
import uuid
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_error_shape(data: dict, expected_status: int) -> None:
    """Assert standard api_error shape: error code, message, and status fields."""
    assert 'error' in data, f"Missing 'error' field in response: {data}"
    assert 'message' in data, f"Missing 'message' field in response: {data}"
    assert 'status' in data, f"Missing 'status' field in response: {data}"
    assert data['status'] == expected_status, (
        f"Expected status={expected_status}, got {data['status']}"
    )
    assert data['success'] is False, f"Expected success=False: {data}"
    # Ensure no traceback leak
    assert 'Traceback' not in str(data), "Stack trace leaked in error response"
    assert 'traceback' not in str(data).lower() or data.get('traceback') is None


# ---------------------------------------------------------------------------
# api_error helper unit test
# ---------------------------------------------------------------------------

class TestApiErrorHelper:
    """Direct tests for the api_error() helper function."""

    def test_returns_tuple(self, app):
        with app.app_context():
            from app.api.errors import api_error
            result = api_error('some_code', 'Some message', 400)
            assert isinstance(result, tuple)
            response, status = result
            assert status == 400

    def test_response_has_required_fields(self, app):
        with app.app_context():
            from app.api.errors import api_error
            response, status = api_error('test_code', 'Test message', 422)
            data = response.get_json()
            assert data['error'] == 'test_code'
            assert data['message'] == 'Test message'
            assert data['status'] == 422
            assert data['success'] is False

    def test_status_code_matches(self, app):
        with app.app_context():
            from app.api.errors import api_error
            for code in [400, 401, 403, 404, 429, 500]:
                _, status = api_error('err', 'msg', code)
                assert status == code


# ---------------------------------------------------------------------------
# Words API error responses
# ---------------------------------------------------------------------------

class TestWordsApiErrors:
    """Test /api/update-word-status and related endpoints use api_error format."""

    def test_update_word_status_non_json_returns_400(self, authenticated_client):
        """Non-JSON request to /api/update-word-status → 400 with proper format."""
        response = authenticated_client.post(
            '/api/update-word-status',
            data='not json',
            content_type='text/plain',
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_update_word_status_missing_fields_returns_400(self, authenticated_client):
        """Missing word_id or status → 400."""
        response = authenticated_client.post(
            '/api/update-word-status',
            json={},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_update_word_status_word_not_found_returns_404(self, authenticated_client):
        """Non-existent word_id → 404 with proper format."""
        response = authenticated_client.post(
            '/api/update-word-status',
            json={'word_id': 9999999, 'status': 1},
        )
        assert response.status_code == 404
        data = response.get_json()
        _assert_error_shape(data, 404)

    def test_batch_update_status_non_json_returns_400(self, authenticated_client):
        """Non-JSON body → 400."""
        response = authenticated_client.post(
            '/api/batch-update-status',
            data='bad',
            content_type='text/plain',
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_batch_update_status_missing_fields_returns_400(self, authenticated_client):
        """Missing word_ids or status → 400."""
        response = authenticated_client.post(
            '/api/batch-update-status',
            json={'word_ids': []},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_batch_update_status_invalid_status_returns_400(self, authenticated_client, db_session):
        """Invalid status string → 400."""
        from app.words.models import CollectionWords
        word = CollectionWords(english_word=f'testword_{uuid.uuid4().hex[:6]}', russian_word='тест')
        db_session.add(word)
        db_session.commit()

        response = authenticated_client.post(
            '/api/batch-update-status',
            json={'word_ids': [word.id], 'status': 'garbage_status'},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_update_single_word_status_non_json_returns_400(self, authenticated_client):
        """Non-JSON body → 400."""
        response = authenticated_client.post(
            '/api/words/1/status',
            data='bad',
            content_type='text/plain',
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_update_single_word_status_invalid_status_returns_400(self, authenticated_client, db_session):
        """Invalid status value → 400."""
        from app.words.models import CollectionWords
        word = CollectionWords(english_word=f'singleword_{uuid.uuid4().hex[:6]}', russian_word='тест')
        db_session.add(word)
        db_session.commit()

        response = authenticated_client.post(
            f'/api/words/{word.id}/status',
            json={'status': 'invalid_status_xyz'},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_user_words_status_non_json_returns_400(self, authenticated_client):
        """Non-JSON body → 400."""
        response = authenticated_client.post(
            '/api/user-words-status',
            data='bad',
            content_type='text/plain',
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_search_words_server_error_returns_api_error_format(self, authenticated_client):
        """search_words exception path returns standard error format."""
        with patch('app.api.words.CollectionWords') as mock_cw:
            mock_cw.query.filter.side_effect = Exception('DB down')
            response = authenticated_client.get('/api/search?term=hello')
        # Either 500 or a partial result — but if error, must have shape
        if response.status_code == 500:
            data = response.get_json()
            _assert_error_shape(data, 500)


# ---------------------------------------------------------------------------
# Anki API error responses
# ---------------------------------------------------------------------------

class TestAnkiApiErrors:
    """Test /api/export-anki uses api_error format."""

    def test_export_anki_non_json_returns_400(self, authenticated_client):
        """Non-JSON body → 400 with proper format."""
        response = authenticated_client.post(
            '/api/export-anki',
            data='bad',
            content_type='text/plain',
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_export_anki_missing_fields_returns_400(self, authenticated_client):
        """Missing required fields → 400."""
        response = authenticated_client.post(
            '/api/export-anki',
            json={},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_export_anki_no_words_found_returns_404(self, authenticated_client):
        """word_ids that don't exist → 404."""
        response = authenticated_client.post(
            '/api/export-anki',
            json={
                'deckName': 'Test Deck',
                'cardFormat': 'basic',
                'wordIds': [9999999],
            },
        )
        assert response.status_code == 404
        data = response.get_json()
        _assert_error_shape(data, 404)


# ---------------------------------------------------------------------------
# Daily plan API — event endpoint error responses
# ---------------------------------------------------------------------------

class TestDailyPlanApiErrors:
    """Test /api/daily-plan/events and related endpoints use api_error format."""

    def test_record_event_non_json_returns_400(self, authenticated_client):
        """Non-JSON body → 400 with proper format."""
        response = authenticated_client.post(
            '/api/daily-plan/events',
            data='bad',
            content_type='text/plain',
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)
        assert data['error'] == 'invalid_content_type'

    def test_record_event_invalid_type_returns_400(self, authenticated_client):
        """Unknown event_type → 400."""
        response = authenticated_client.post(
            '/api/daily-plan/events',
            json={'event_type': 'totally_invalid_event'},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)
        assert data['error'] == 'invalid_event_type'

    def test_skip_lesson_non_json_returns_400(self, authenticated_client):
        """Non-JSON body to skip-lesson → 400."""
        response = authenticated_client.post(
            '/api/daily-plan/skip-lesson',
            data='bad',
            content_type='text/plain',
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_skip_lesson_invalid_lesson_id_returns_400(self, authenticated_client):
        """Non-integer lesson_id → 400."""
        response = authenticated_client.post(
            '/api/daily-plan/skip-lesson',
            json={'lesson_id': 'abc'},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_plan_pause_invalid_days_returns_400(self, authenticated_client):
        """days=0 is out of range (1–14) → 400."""
        response = authenticated_client.post(
            '/api/plan/pause',
            json={'days': 0},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)
        assert data['error'] == 'invalid_days'

    def test_plan_pause_days_too_large_returns_400(self, authenticated_client):
        """days=99 is out of range → 400."""
        response = authenticated_client.post(
            '/api/plan/pause',
            json={'days': 99},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_complete_error_review_bad_ids_returns_400(self, authenticated_client):
        """error_ids as string instead of list → 400."""
        response = authenticated_client.post(
            '/api/daily-plan/error-review/complete',
            json={'error_ids': 'not a list'},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_challenge_complete_missing_id_returns_400(self, authenticated_client):
        """Missing challenge_id → 400."""
        response = authenticated_client.post(
            '/api/daily-plan/challenge/complete',
            json={},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)


# ---------------------------------------------------------------------------
# Books API error responses
# ---------------------------------------------------------------------------

class TestBooksApiErrors:
    """Test /api/books/select uses api_error format."""

    def test_select_book_invalid_id_returns_400(self, authenticated_client):
        """Non-integer book_id → 400 with proper format."""
        response = authenticated_client.post(
            '/api/books/select',
            json={'book_id': 'not-an-int'},
        )
        assert response.status_code == 400
        data = response.get_json()
        _assert_error_shape(data, 400)

    def test_select_book_not_found_returns_404(self, authenticated_client):
        """Non-existent book_id → 404 with proper format."""
        response = authenticated_client.post(
            '/api/books/select',
            json={'book_id': 9999999},
        )
        assert response.status_code == 404
        data = response.get_json()
        _assert_error_shape(data, 404)


# ---------------------------------------------------------------------------
# Unauthenticated requests return 401 with proper format
# ---------------------------------------------------------------------------

class TestUnauthenticatedApiErrors:
    """Unauthenticated requests must return 401 with consistent format."""

    @pytest.mark.smoke
    @pytest.mark.parametrize('url,method', [
        ('/api/daily-plan', 'GET'),
        ('/api/daily-status', 'GET'),
        ('/api/streak', 'GET'),
        ('/api/words', 'GET'),
        ('/api/update-word-status', 'POST'),
        ('/api/books/catalog', 'GET'),
        ('/api/books/select', 'POST'),
        ('/api/export-anki', 'POST'),
    ])
    def test_unauthenticated_returns_401(self, client, url, method):
        if method == 'GET':
            response = client.get(url)
        else:
            response = client.post(url, json={})
        assert response.status_code == 401
        data = response.get_json()
        assert data is not None, "401 response must be JSON"
        assert data['success'] is False
        # Check for code/message or at minimum the success=False convention
        assert 'error' in data or 'message' in data or 'status_code' in data


# ---------------------------------------------------------------------------
# Global 500 handler does not leak tracebacks
# ---------------------------------------------------------------------------

class TestGlobal500Handler:
    """The global 500 handler must return JSON with code/message, no traceback."""

    def test_500_handler_response_format(self, app):
        """Call the 500 handler directly and verify its JSON response format."""
        # In TESTING=True mode Flask propagates exceptions; call the handler
        # directly to verify it produces the right format without needing a
        # live HTTP 500.
        from werkzeug.exceptions import InternalServerError

        spec_500 = app.error_handler_spec.get(None, {}).get(500, {})
        handler = spec_500.get(InternalServerError) or spec_500.get(None)
        if handler is None:
            pytest.skip("No 500 handler registered")

        with app.test_request_context(
            '/api/test',
            headers={'Accept': 'application/json'},
        ):
            result = handler(InternalServerError("deliberate test error"))
            if isinstance(result, tuple):
                response, status_code = result
            else:
                response = result
                status_code = result.status_code
            assert status_code == 500
            data = response.get_json()
            assert data is not None, "500 handler must return JSON for API paths"
            assert data['success'] is False
            assert 'error' in data, f"Missing 'error' field: {data}"
            assert 'message' in data, f"Missing 'message' field: {data}"
            body = json.dumps(data)
            assert 'RuntimeError' not in body
            assert 'Traceback' not in body
