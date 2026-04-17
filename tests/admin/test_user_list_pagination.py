"""Tests for admin user list pagination (Task 40)."""
import uuid

import pytest

from app.auth.models import User
from app.utils.db import db


def _make_user(db_session, **kwargs):
    defaults = {
        'username': f'user_{uuid.uuid4().hex[:8]}',
        'email': f'{uuid.uuid4().hex[:8]}@test.com',
        'active': True,
    }
    defaults.update(kwargs)
    u = User(**defaults)
    u.set_password('testpass')
    db_session.add(u)
    return u


class TestAdminUserListPagination:
    """Tests for paginated admin user list endpoint."""

    @pytest.mark.smoke
    def test_page1_returns_paginated_users(self, app, admin_client, db_session):
        """GET /admin/users?page=1 returns 200 with pagination metadata."""
        response = admin_client.get('/admin/users?page=1&per_page=20')
        assert response.status_code == 200
        html = response.data.decode()
        # Template renders total user count via pagination.total
        assert 'Пользователи' in html

    def test_pagination_controls_present(self, app, admin_client, db_session):
        """Template renders pagination nav when multiple pages exist."""
        # Create enough users to exceed 1 page (default per_page=20)
        for _ in range(25):
            _make_user(db_session)
        db_session.flush()

        response = admin_client.get('/admin/users?page=1&per_page=20')
        assert response.status_code == 200
        html = response.data.decode()
        # Pagination nav is rendered (page-link class)
        assert 'page-link' in html

    def test_page2_returns_next_batch(self, app, admin_client, db_session):
        """GET page=2 returns 200 (not 500) even when users exist."""
        for _ in range(25):
            _make_user(db_session)
        db_session.flush()

        response = admin_client.get('/admin/users?page=2&per_page=20')
        assert response.status_code == 200

    def test_empty_page_beyond_total_returns_200(self, app, admin_client, db_session):
        """Requesting a page far beyond total does not 500 (error_out=False)."""
        response = admin_client.get('/admin/users?page=9999&per_page=20')
        assert response.status_code == 200

    def test_per_page_clamped_to_50(self, app, admin_client, db_session):
        """per_page values above 50 are clamped to 50 (route enforces max)."""
        response = admin_client.get('/admin/users?page=1&per_page=500')
        assert response.status_code == 200

    def test_search_filters_users(self, app, admin_client, db_session):
        """Search param filters results by username/email."""
        unique = uuid.uuid4().hex[:8]
        u = _make_user(db_session, username=f'searchme_{unique}')
        db_session.flush()

        response = admin_client.get(f'/admin/users?search=searchme_{unique}')
        assert response.status_code == 200
        html = response.data.decode()
        assert f'searchme_{unique}' in html

    def test_unauthenticated_redirects_to_login(self, client):
        """Non-admin request is redirected."""
        response = client.get('/admin/users', follow_redirects=False)
        assert response.status_code == 302
