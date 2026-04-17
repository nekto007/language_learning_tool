"""
Tests for per-record error reporting in batch admin operations.
Covers: bulk_course_operations in app/admin/book_courses.py
"""
import json
import pytest
from unittest.mock import patch, MagicMock, call


@pytest.fixture
def mock_admin_user(admin_user):
    """Mock current_user as authenticated admin."""
    with patch('app.admin.utils.decorators.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.id = admin_user.id
        mock_user.username = admin_user.username
        yield mock_user


class TestBulkCourseOperationsErrorReporting:
    """Tests for bulk_course_operations per-record error reporting."""

    @pytest.mark.smoke
    def test_bulk_activate_all_valid_returns_no_errors(self, admin_client, mock_admin_user):
        """All valid courses: returns success_count == N and errors == []."""
        course1 = MagicMock(id=1, title='Course 1', modules=[])
        course2 = MagicMock(id=2, title='Course 2', modules=[])

        with patch('app.admin.book_courses.BookCourse') as mock_bc, \
             patch('app.admin.book_courses.db') as mock_db:
            mock_bc.query.filter.return_value.all.return_value = [course1, course2]
            mock_db.session.flush.return_value = None
            mock_db.session.commit.return_value = None
            mock_db.session.rollback.return_value = None

            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'activate', 'course_ids': '1,2'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['success_count'] == 2
        assert data['errors'] == []

    def test_bulk_deactivate_all_valid_returns_no_errors(self, admin_client, mock_admin_user):
        """Deactivate: all valid courses, no errors reported."""
        course1 = MagicMock(id=10, title='C1', modules=[])

        with patch('app.admin.book_courses.BookCourse') as mock_bc, \
             patch('app.admin.book_courses.db') as mock_db:
            mock_bc.query.filter.return_value.all.return_value = [course1]
            mock_db.session.flush.return_value = None
            mock_db.session.commit.return_value = None
            mock_db.session.rollback.return_value = None

            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'deactivate', 'course_ids': '10'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['success_count'] == 1
        assert data['errors'] == []

    def test_bulk_with_one_failing_record_returns_partial_success(self, admin_client, mock_admin_user):
        """1 valid + 1 invalid: returns success_count=1 and errors list with 1 entry."""
        course_ok = MagicMock(id=1, title='Good Course', modules=[])
        course_bad = MagicMock(id=2, title='Bad Course', modules=[])

        call_count = [0]

        def begin_nested_side_effect():
            call_count[0] += 1
            nested = MagicMock()
            if call_count[0] == 2:
                nested.commit.side_effect = Exception("DB constraint violation")
            return nested

        with patch('app.admin.book_courses.BookCourse') as mock_bc, \
             patch('app.admin.book_courses.db') as mock_db:
            mock_bc.query.filter.return_value.all.return_value = [course_ok, course_bad]
            mock_db.session.begin_nested.side_effect = begin_nested_side_effect
            mock_db.session.commit.return_value = None

            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'activate', 'course_ids': '1,2'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True
        assert data['success_count'] == 1
        assert len(data['errors']) == 1
        assert data['errors'][0]['course_id'] == 2
        assert 'error' in data['errors'][0]

    def test_bulk_all_failing_records_returns_zero_success(self, admin_client, mock_admin_user):
        """All records fail: success_count == 0, errors list has all entries."""
        course1 = MagicMock(id=3, title='Course 3', modules=[])
        course2 = MagicMock(id=4, title='Course 4', modules=[])

        def begin_nested_side_effect():
            nested = MagicMock()
            nested.commit.side_effect = Exception("always fails")
            return nested

        with patch('app.admin.book_courses.BookCourse') as mock_bc, \
             patch('app.admin.book_courses.db') as mock_db:
            mock_bc.query.filter.return_value.all.return_value = [course1, course2]
            mock_db.session.begin_nested.side_effect = begin_nested_side_effect
            mock_db.session.commit.return_value = None

            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'feature', 'course_ids': '3,4'},
            )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['success'] is True  # the endpoint itself succeeded
        assert data['success_count'] == 0
        assert len(data['errors']) == 2

    def test_bulk_unknown_operation_returns_400(self, admin_client, mock_admin_user):
        """Unknown operation returns 400 before processing any records."""
        with patch('app.admin.book_courses.BookCourse'):
            response = admin_client.post(
                '/admin/book-courses/bulk-operations',
                data={'operation': 'unknown_op', 'course_ids': '1'},
            )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False

    def test_bulk_empty_course_ids_returns_400(self, admin_client, mock_admin_user):
        """No course_ids returns 400."""
        response = admin_client.post(
            '/admin/book-courses/bulk-operations',
            data={'operation': 'activate', 'course_ids': ''},
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert data['success'] is False
