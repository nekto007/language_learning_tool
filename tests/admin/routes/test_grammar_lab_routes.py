# tests/admin/routes/test_grammar_lab_routes.py
"""Tests for admin grammar lab routes — duplicate detection (Task 22)."""
import pytest
from unittest.mock import patch
from sqlalchemy.exc import IntegrityError


class TestCreateTopicDuplicateSlug:
    """Tests for duplicate slug detection in create_topic route."""

    @pytest.mark.smoke
    @patch('app.admin.routes.grammar_lab_routes.db')
    def test_create_topic_duplicate_slug_returns_error_flash(self, mock_db, admin_client, mock_admin_user):
        """Duplicate slug triggers IntegrityError which flashes an error message."""
        mock_db.session.add.return_value = None
        mock_db.session.commit.side_effect = IntegrityError(
            statement='INSERT INTO grammar_topics', params={}, orig=Exception('unique constraint')
        )
        mock_db.session.rollback.return_value = None

        response = admin_client.post(
            '/admin/grammar-lab/topics/create',
            data={
                'slug': 'a1-1',
                'title': 'Present Simple',
                'title_ru': 'Настоящее простое',
                'level': 'A1',
                'order': '1',
                'estimated_time': '15',
                'difficulty': '1',
                'content': '{}'
            },
            follow_redirects=True
        )

        assert response.status_code == 200
        assert b'slug' in response.data or b'taken' in response.data or b'Error' in response.data

    @patch('app.admin.routes.grammar_lab_routes.db')
    def test_create_topic_rollback_called_on_integrity_error(self, mock_db, admin_client, mock_admin_user):
        """Ensure rollback is called on IntegrityError so session stays clean."""
        mock_db.session.add.return_value = None
        mock_db.session.commit.side_effect = IntegrityError(
            statement='INSERT', params={}, orig=Exception('unique constraint')
        )
        mock_db.session.rollback.return_value = None

        admin_client.post(
            '/admin/grammar-lab/topics/create',
            data={
                'slug': 'a1-1',
                'title': 'Test',
                'title_ru': 'Тест',
                'level': 'A1',
                'order': '1',
                'estimated_time': '15',
                'difficulty': '1',
                'content': '{}'
            },
            follow_redirects=True
        )

        mock_db.session.rollback.assert_called_once()
