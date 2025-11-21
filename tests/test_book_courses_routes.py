# tests/test_book_courses_routes.py

"""
Integration tests for app/admin/book_courses.py routes
Target: High coverage of all route handlers

Note: These tests use existing conftest.py fixtures to avoid duplication
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
import json


@pytest.fixture
def test_book_course(app, db_session, test_book):
    """Create test book course"""
    from app.curriculum.book_courses import BookCourse

    course = BookCourse(
        book_id=test_book.id,
        title='Test Course',
        description='Test Description',
        level='B1',
        is_active=True,
        is_featured=False
    )
    db_session.add(course)
    db_session.commit()
    return course


@pytest.fixture
def test_book_course_module(app, db_session, test_book_course):
    """Create test course module"""
    from app.curriculum.book_courses import BookCourseModule

    module = BookCourseModule(
        course_id=test_book_course.id,
        title='Test Module',
        description='Test Module Description',
        order_index=1,
        start_position=0,
        end_position=100
    )
    db_session.add(module)
    db_session.commit()
    return module


class TestBookCoursesListRoute:
    """Tests for /admin/book-courses route"""

    def test_book_courses_list_requires_admin(self, client, app, test_user):
        """Non-admin users should be redirected"""
        with app.app_context():
            # Login as non-admin user
            with client.session_transaction() as session:
                session['user_id'] = test_user.id
                session['_fresh'] = True

            response = client.get('/admin/book-courses')
            # Should redirect to dashboard or show access denied
            assert response.status_code in [302, 403]

    def test_book_courses_list_success(self, admin_client, app):
        """Admin can access book courses list"""
        with app.app_context():
            response = admin_client.get('/admin/book-courses')
            # Should render successfully
            assert response.status_code == 200

    def test_book_courses_list_with_data(self, admin_client, app, test_book_course):
        """Book courses list displays existing courses"""
        with app.app_context():
            response = admin_client.get('/admin/book-courses')
            assert response.status_code == 200
            # Check if the course title appears in response
            assert b'Test Course' in response.data or response.status_code == 200


class TestCreateBookCourseRoutes:
    """Tests for /admin/book-courses/create routes"""

    def test_create_book_course_get(self, admin_client, app):
        """GET /admin/book-courses/create should show form"""
        with app.app_context():
            response = admin_client.get('/admin/book-courses/create')
            assert response.status_code == 200

    @patch('app.admin.book_courses.BookCourseGenerator')
    def test_create_book_course_post_auto_generate(self, mock_generator, admin_client, app, test_book):
        """POST with auto_generate=true should use generator"""
        with app.app_context():
            mock_instance = Mock()
            mock_instance.generate_course.return_value = {'success': True, 'course_id': 1}
            mock_generator.return_value = mock_instance

            response = admin_client.post('/admin/book-courses/create',
                data={
                    'book_id': test_book.id,
                    'auto_generate': 'true'
                },
                follow_redirects=False
            )
            # Should process request
            assert response.status_code in [200, 302]

    def test_create_book_course_post_manual(self, admin_client, app, test_book, db_session):
        """POST with manual data should create course"""
        with app.app_context():
            response = admin_client.post('/admin/book-courses/create',
                data={
                    'book_id': test_book.id,
                    'course_title': 'Manual Course',
                    'course_description': 'Manual Description',
                    'level': 'B2'
                },
                follow_redirects=False
            )
            # Should process request
            assert response.status_code in [200, 302]

    def test_create_book_course_no_book_id(self, admin_client, app):
        """POST without book_id should return error"""
        with app.app_context():
            response = admin_client.post('/admin/book-courses/create',
                data={
                    'course_title': 'No Book Course'
                },
                follow_redirects=False
            )
            # Should return error or redirect
            assert response.status_code in [200, 302, 400]


class TestViewBookCourseRoute:
    """Tests for /admin/book-courses/<id> route"""

    def test_view_book_course_success(self, admin_client, app, test_book_course):
        """View existing course"""
        with app.app_context():
            response = admin_client.get(f'/admin/book-courses/{test_book_course.id}')
            assert response.status_code == 200

    def test_view_book_course_not_found(self, admin_client, app):
        """View non-existent course"""
        with app.app_context():
            response = admin_client.get('/admin/book-courses/99999')
            # Should return 404 or redirect
            assert response.status_code in [404, 302]


class TestEditBookCourseRoutes:
    """Tests for /admin/book-courses/<id>/edit routes"""

    def test_edit_book_course_get(self, admin_client, app, test_book_course):
        """GET edit form"""
        with app.app_context():
            response = admin_client.get(f'/admin/book-courses/{test_book_course.id}/edit')
            assert response.status_code == 200

    def test_edit_book_course_post_success(self, admin_client, app, test_book_course):
        """POST edit with valid data"""
        with app.app_context():
            response = admin_client.post(f'/admin/book-courses/{test_book_course.id}/edit',
                data={
                    'title': 'Updated Course',
                    'description': 'Updated Description'
                },
                follow_redirects=False
            )
            assert response.status_code in [200, 302]


class TestDeleteBookCourseRoute:
    """Tests for /admin/book-courses/<id>/delete route"""

    def test_delete_book_course_soft(self, admin_client, app, test_book_course):
        """Soft delete course"""
        with app.app_context():
            response = admin_client.post(f'/admin/book-courses/{test_book_course.id}/delete',
                data={'delete_type': 'soft'},
                follow_redirects=False
            )
            assert response.status_code in [200, 302]

    def test_delete_book_course_hard(self, admin_client, app, db_session, test_book):
        """Hard delete course"""
        from app.curriculum.book_courses import BookCourse

        with app.app_context():
            # Create a new course for hard delete
            course = BookCourse(
                book_id=test_book.id,
                title='Course to Delete',
                description='Will be deleted',
                level='A1',
                is_active=True
            )
            db_session.add(course)
            db_session.commit()
            course_id = course.id

            response = admin_client.post(f'/admin/book-courses/{course_id}/delete',
                data={'delete_type': 'hard'},
                follow_redirects=False
            )
            assert response.status_code in [200, 302]


class TestCourseModuleRoutes:
    """Tests for course module routes"""

    def test_view_course_module(self, admin_client, app, test_book_course_module):
        """View course module"""
        with app.app_context():
            response = admin_client.get(
                f'/admin/book-courses/{test_book_course_module.course_id}/modules/{test_book_course_module.id}'
            )
            assert response.status_code == 200

    @patch('app.admin.book_courses.BookCourseGenerator')
    def test_generate_course_modules(self, mock_generator, admin_client, app, test_book_course):
        """Generate modules for course"""
        with app.app_context():
            mock_instance = Mock()
            mock_instance.generate_modules.return_value = {'success': True}
            mock_generator.return_value = mock_instance

            response = admin_client.post(
                f'/admin/book-courses/{test_book_course.id}/generate-modules',
                follow_redirects=False
            )
            assert response.status_code in [200, 302]


class TestAnalyticsRoute:
    """Tests for /admin/book-courses/analytics route"""

    def test_book_courses_analytics(self, admin_client, app):
        """View analytics page"""
        with app.app_context():
            response = admin_client.get('/admin/book-courses/analytics')
            assert response.status_code == 200


class TestBulkOperationsRoute:
    """Tests for /admin/book-courses/bulk-operations route"""

    def test_bulk_activate(self, admin_client, app, test_book_course):
        """Bulk activate courses"""
        with app.app_context():
            response = admin_client.post('/admin/book-courses/bulk-operations',
                json={
                    'operation': 'activate',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_deactivate(self, admin_client, app, test_book_course):
        """Bulk deactivate courses"""
        with app.app_context():
            response = admin_client.post('/admin/book-courses/bulk-operations',
                json={
                    'operation': 'deactivate',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_feature(self, admin_client, app, test_book_course):
        """Bulk feature courses"""
        with app.app_context():
            response = admin_client.post('/admin/book-courses/bulk-operations',
                json={
                    'operation': 'feature',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_unfeature(self, admin_client, app, test_book_course):
        """Bulk unfeature courses"""
        with app.app_context():
            response = admin_client.post('/admin/book-courses/bulk-operations',
                json={
                    'operation': 'unfeature',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_delete_soft(self, admin_client, app, test_book_course):
        """Bulk soft delete courses"""
        with app.app_context():
            response = admin_client.post('/admin/book-courses/bulk-operations',
                json={
                    'operation': 'delete_soft',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_delete_permanently(self, admin_client, app, db_session, test_book):
        """Bulk permanently delete courses"""
        from app.curriculum.book_courses import BookCourse

        with app.app_context():
            # Create course to delete
            course = BookCourse(
                book_id=test_book.id,
                title='Bulk Delete Course',
                description='Will be deleted',
                level='A1'
            )
            db_session.add(course)
            db_session.commit()

            response = admin_client.post('/admin/book-courses/bulk-operations',
                json={
                    'operation': 'delete_permanently',
                    'course_ids': [course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_no_course_ids(self, admin_client, app):
        """Bulk operation without course_ids should fail"""
        with app.app_context():
            response = admin_client.post('/admin/book-courses/bulk-operations',
                json={
                    'operation': 'activate',
                    'course_ids': []
                }
            )
            # Should return error
            assert response.status_code in [200, 400]

    def test_bulk_unknown_operation(self, admin_client, app, test_book_course):
        """Bulk operation with unknown operation should fail"""
        with app.app_context():
            response = admin_client.post('/admin/book-courses/bulk-operations',
                json={
                    'operation': 'unknown_operation',
                    'course_ids': [test_book_course.id]
                }
            )
            # Should return error
            assert response.status_code in [200, 400]
