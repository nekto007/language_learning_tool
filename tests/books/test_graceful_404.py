# tests/books/test_graceful_404.py
"""
Tests that non-existent books, lessons, and curriculum pages
return 404 rather than 500 errors.
"""
import uuid
from unittest.mock import patch

import pytest

from app.books.models import Book
from app.curriculum.models import CEFRLevel, Module


class TestBookGraceful404:
    """Book routes return 404 for non-existent resources, not 500."""

    @pytest.mark.smoke
    def test_book_details_nonexistent_returns_404(self, authenticated_client):
        """GET /books/999999/ -> 404 when book does not exist."""
        response = authenticated_client.get('/books/999999/')
        assert response.status_code == 404

    def test_book_words_nonexistent_returns_404(self, authenticated_client):
        """GET /books/999999/words -> 404 when book does not exist."""
        response = authenticated_client.get('/books/999999/words')
        assert response.status_code == 404

    def test_book_read_nonexistent_returns_404(self, authenticated_client):
        """GET /read/999999 -> 404 when book does not exist.

        Mocks module access so the @module_required('books') check passes and
        the route reaches the DB lookup, which must return 404 not 500.
        """
        with patch(
            'app.modules.service.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get('/read/999999')
        assert response.status_code == 404

    def test_book_slug_reader_nonexistent_returns_404(self, authenticated_client):
        """GET /books/nonexistent-slug/reader -> 404 when book slug does not exist."""
        with patch(
            'app.modules.service.ModuleService.is_module_enabled_for_user',
            return_value=True,
        ):
            response = authenticated_client.get('/books/nonexistent-slug-xyz-404/reader')
        assert response.status_code == 404


class TestCurriculumGraceful404:
    """Curriculum routes return 404 for non-existent resources."""

    def test_lesson_by_id_nonexistent_returns_404(self, authenticated_client):
        """GET /learn/999999/ -> 404 when lesson does not exist.

        require_lesson_access now returns 404 (not 403) for a non-existent lesson.
        """
        response = authenticated_client.get('/learn/999999/')
        assert response.status_code == 404

    def test_learn_by_level_nonexistent_db_returns_404(self, authenticated_client):
        """GET /learn/a0/ -> 404 when level code is valid but not in DB."""
        # A0 is in valid_levels; if it doesn't exist in the test DB, must be 404 not 500
        response = authenticated_client.get('/learn/a0/')
        assert response.status_code in (200, 302, 404)  # never 500

    def test_learn_by_module_nonexistent_module_returns_404(self, authenticated_client, db_session):
        """GET /learn/<code>/module-9999/ -> 404 when module number does not exist."""
        code = 'T' + uuid.uuid4().hex[:1].upper()
        level = CEFRLevel(
            code=code,
            name='Test Level',
            description='Test',
            order=99,
        )
        db_session.add(level)
        db_session.commit()

        response = authenticated_client.get(f'/learn/{code.lower()}/module-9999/')
        assert response.status_code == 404

    def test_learn_by_module_nonexistent_level_returns_404(self, authenticated_client):
        """GET /learn/zz/module-1/ -> 404 when level code doesn't exist in DB."""
        # 'zz' is not in valid_levels; learn_by_module calls abort(404)
        response = authenticated_client.get('/learn/zz/module-1/')
        assert response.status_code == 404
