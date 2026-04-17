"""Tests for gzip compression on /health and large API responses.

Task 62: Verifies that Flask-Compress middleware compresses eligible responses
when the client sends Accept-Encoding: gzip.
"""
import gzip
import json
import pytest
from unittest.mock import patch


class TestGzipCompression:
    """Verify gzip Content-Encoding is applied when client requests it."""

    @pytest.mark.smoke
    def test_health_endpoint_compressed_when_gzip_requested(self, client, app):
        """GET /health with Accept-Encoding: gzip returns a gzip-compressed response.

        The /health payload is small (~26 bytes), which is below the default
        COMPRESS_MIN_SIZE of 500. We temporarily lower the threshold to 1 so
        that the compression middleware actually fires, letting us assert the
        Content-Encoding header and verify the body round-trips correctly.
        """
        original_min_size = app.config.get('COMPRESS_MIN_SIZE', 500)
        app.config['COMPRESS_MIN_SIZE'] = 1
        try:
            response = client.get(
                '/health',
                headers={'Accept-Encoding': 'gzip, deflate'},
            )
            assert response.status_code == 200
            assert response.headers.get('Content-Encoding') == 'gzip', (
                "Expected Content-Encoding: gzip, got: "
                + repr(response.headers.get('Content-Encoding'))
            )
            # Manually decompress since Flask test client does not auto-decompress
            body = json.loads(gzip.decompress(response.data))
            assert body['status'] == 'ok'
            assert body['db'] == 'ok'
        finally:
            app.config['COMPRESS_MIN_SIZE'] = original_min_size

    def test_large_api_response_has_gzip_encoding_header(self, authenticated_client):
        """Large /api/daily-plan response has Content-Encoding: gzip header.

        A mock plan payload that exceeds COMPRESS_MIN_SIZE (default 500 bytes)
        is injected so Flask-Compress fires without overriding the threshold.
        """
        # Build a plan payload definitely larger than 500 bytes
        large_plan = {
            'next_lesson': None,
            'grammar_topic': None,
            'words_due': 0,
            'has_any_words': False,
            'book_to_read': None,
            'suggested_books': [
                {'id': i, 'title': f'Book Title {i}', 'author': f'Author {i}',
                 'description': 'A compelling book about language learning ' * 2}
                for i in range(5)
            ],
            'book_course_lesson': None,
            'book_course_done_today': False,
            'onboarding': None,
            'bonus': [
                {'type': 'grammar', 'topic_id': i, 'title': f'Bonus Topic {i}',
                 'description': 'Practice your grammar skills with this exercise'}
                for i in range(3)
            ],
            'mission': None,
        }
        payload_size = len(json.dumps({'success': True, **large_plan}))
        assert payload_size > 500, (
            f"Test payload ({payload_size} bytes) must exceed COMPRESS_MIN_SIZE=500"
        )

        with patch('app.daily_plan.service.get_daily_plan_unified', return_value=large_plan):
            response = authenticated_client.get(
                '/api/daily-plan',
                headers={'Accept-Encoding': 'gzip, deflate'},
            )

        assert response.status_code == 200
        assert response.headers.get('Content-Encoding') == 'gzip', (
            "Expected Content-Encoding: gzip for large API response, got: "
            + repr(response.headers.get('Content-Encoding'))
        )
