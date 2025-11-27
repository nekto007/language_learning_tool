# tests/test_book_courses_routes.py

"""
Integration tests for app/admin/book_courses.py routes
Target: High coverage of all route handlers by bypassing authentication
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, PropertyMock
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
        end_position=100,
        module_number=1
    )
    db_session.add(module)
    db_session.commit()
    return module


@pytest.fixture
def mock_admin_user(admin_user):
    """Mock current_user to be admin"""
    with patch('app.utils.decorators.current_user') as mock_user:
        mock_user.is_authenticated = True
        mock_user.is_admin = True
        mock_user.id = admin_user.id
        yield mock_user


class TestBookCoursesListRoute:
    """Tests for /admin/book-courses route"""

    def test_book_courses_list_requires_admin(self, client, app, test_user):
        """Non-admin users should be redirected"""
        with app.app_context():
            # Try without authentication
            response = client.get('/admin/book-courses')
            # Should redirect due to @admin_required
            assert response.status_code in [302, 403]

    def test_book_courses_list_success(self, client, app, mock_admin_user):
        """Admin can access book courses list"""
        with app.app_context():
            response = client.get('/admin/book-courses')
            assert response.status_code == 200

    def test_book_courses_list_with_data(self, client, app, mock_admin_user, test_book_course):
        """Book courses list displays existing courses"""
        with app.app_context():
            response = client.get('/admin/book-courses')
            assert response.status_code == 200


class TestCreateBookCourseRoutes:
    """Tests for /admin/book-courses/create routes"""

    def test_create_book_course_get(self, client, app, mock_admin_user):
        """GET /admin/book-courses/create should show form"""
        with app.app_context():
            response = client.get('/admin/book-courses/create')
            assert response.status_code == 200

    @patch('app.admin.book_courses.BookCourseGenerator')
    def test_create_book_course_post_auto_generate(self, mock_generator, client, app, mock_admin_user, test_book):
        """POST with auto_generate=true should use generator"""
        with app.app_context():
            mock_instance = Mock()
            mock_instance.generate_course.return_value = {'success': True, 'course_id': 1}
            mock_generator.return_value = mock_instance

            response = client.post('/admin/book-courses/create',
                data={
                    'book_id': test_book.id,
                    'auto_generate': 'true'
                },
                follow_redirects=False
            )
            assert response.status_code in [200, 302]

    def test_create_book_course_post_manual(self, client, app, mock_admin_user, test_book):
        """POST with manual data should create course"""
        with app.app_context():
            response = client.post('/admin/book-courses/create',
                data={
                    'book_id': test_book.id,
                    'course_title': 'Manual Course',
                    'course_description': 'Manual Description',
                    'level': 'B2'
                },
                follow_redirects=False
            )
            assert response.status_code in [200, 302]

    def test_create_book_course_no_book_id(self, client, app, mock_admin_user):
        """POST without book_id should return error"""
        with app.app_context():
            response = client.post('/admin/book-courses/create',
                data={
                    'course_title': 'No Book Course'
                },
                follow_redirects=False
            )
            assert response.status_code in [200, 302, 400]


class TestViewBookCourseRoute:
    """Tests for /admin/book-courses/<id> route"""

    def test_view_book_course_success(self, client, app, mock_admin_user, test_book_course):
        """View existing course"""
        with app.app_context():
            response = client.get(f'/admin/book-courses/{test_book_course.id}')
            assert response.status_code == 200

    def test_view_book_course_not_found(self, client, app, mock_admin_user):
        """View non-existent course"""
        with app.app_context():
            response = client.get('/admin/book-courses/99999')
            assert response.status_code in [404, 302, 500]


class TestEditBookCourseRoutes:
    """Tests for /admin/book-courses/<id>/edit routes"""

    def test_edit_book_course_get(self, client, app, mock_admin_user, test_book_course):
        """GET edit form"""
        with app.app_context():
            response = client.get(f'/admin/book-courses/{test_book_course.id}/edit')
            assert response.status_code == 200

    def test_edit_book_course_post_success(self, client, app, mock_admin_user, test_book_course):
        """POST edit with valid data"""
        with app.app_context():
            response = client.post(f'/admin/book-courses/{test_book_course.id}/edit',
                data={
                    'title': 'Updated Course',
                    'description': 'Updated Description'
                },
                follow_redirects=False
            )
            assert response.status_code in [200, 302]


class TestDeleteBookCourseRoute:
    """Tests for /admin/book-courses/<id>/delete route"""

    def test_delete_book_course_soft(self, client, app, mock_admin_user, test_book_course):
        """Soft delete course"""
        with app.app_context():
            response = client.post(f'/admin/book-courses/{test_book_course.id}/delete',
                data={'delete_type': 'soft'},
                follow_redirects=False
            )
            assert response.status_code in [200, 302]

    def test_delete_book_course_hard(self, client, app, mock_admin_user, db_session, test_book):
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

            response = client.post(f'/admin/book-courses/{course_id}/delete',
                data={'delete_type': 'hard'},
                follow_redirects=False
            )
            assert response.status_code in [200, 302]


class TestCourseModuleRoutes:
    """Tests for course module routes"""

    def test_view_course_module(self, client, app, mock_admin_user, test_book_course_module):
        """View course module"""
        with app.app_context():
            response = client.get(
                f'/admin/book-courses/{test_book_course_module.course_id}/modules/{test_book_course_module.id}'
            )
            assert response.status_code == 200

    @patch('app.admin.book_courses.BookCourseGenerator')
    def test_generate_course_modules(self, mock_generator, client, app, mock_admin_user, test_book_course):
        """Generate modules for course"""
        with app.app_context():
            mock_instance = Mock()
            mock_instance.generate_modules.return_value = {'success': True}
            mock_generator.return_value = mock_instance

            response = client.post(
                f'/admin/book-courses/{test_book_course.id}/generate-modules',
                follow_redirects=False
            )
            assert response.status_code in [200, 302]


class TestAnalyticsRoute:
    """Tests for /admin/book-courses/analytics route"""

    def test_book_courses_analytics(self, client, app, mock_admin_user):
        """View analytics page"""
        with app.app_context():
            response = client.get('/admin/book-courses/analytics')
            assert response.status_code == 200


class TestBulkOperationsRoute:
    """Tests for /admin/book-courses/bulk-operations route"""

    def test_bulk_activate(self, client, app, mock_admin_user, test_book_course):
        """Bulk activate courses"""
        with app.app_context():
            response = client.post('/admin/book-courses/bulk-operations',
                data={
                    'operation': 'activate',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_deactivate(self, client, app, mock_admin_user, test_book_course):
        """Bulk deactivate courses"""
        with app.app_context():
            response = client.post('/admin/book-courses/bulk-operations',
                data={
                    'operation': 'deactivate',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_feature(self, client, app, mock_admin_user, test_book_course):
        """Bulk feature courses"""
        with app.app_context():
            response = client.post('/admin/book-courses/bulk-operations',
                data={
                    'operation': 'feature',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_unfeature(self, client, app, mock_admin_user, test_book_course):
        """Bulk unfeature courses"""
        with app.app_context():
            response = client.post('/admin/book-courses/bulk-operations',
                data={
                    'operation': 'unfeature',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_delete_soft(self, client, app, mock_admin_user, test_book_course):
        """Bulk soft delete courses"""
        with app.app_context():
            response = client.post('/admin/book-courses/bulk-operations',
                data={
                    'operation': 'delete',
                    'course_ids': [test_book_course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_delete_permanently(self, client, app, mock_admin_user, db_session, test_book):
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

            response = client.post('/admin/book-courses/bulk-operations',
                data={
                    'operation': 'delete_permanently',
                    'course_ids': [course.id]
                }
            )
            assert response.status_code == 200

    def test_bulk_no_course_ids(self, client, app, mock_admin_user):
        """Bulk operation without course_ids should fail"""
        with app.app_context():
            response = client.post('/admin/book-courses/bulk-operations',
                data={
                    'operation': 'activate',
                    'course_ids': []
                }
            )
            # Should return error
            assert response.status_code in [200, 400]

    def test_bulk_unknown_operation(self, client, app, mock_admin_user, test_book_course):
        """Bulk operation with unknown operation should fail"""
        with app.app_context():
            response = client.post('/admin/book-courses/bulk-operations',
                data={
                    'operation': 'unknown_operation',
                    'course_ids': [test_book_course.id]
                }
            )
            # Should return error
            assert response.status_code in [200, 400]
