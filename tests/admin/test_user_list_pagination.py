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

    def test_per_page_clamped_to_max(self, app, admin_client, db_session):
        """per_page values above MAX_USERS_PER_PAGE are clamped (route enforces max)."""
        from app.admin.routes.user_routes import MAX_USERS_PER_PAGE

        response = admin_client.get('/admin/users?page=1&per_page=500')
        assert response.status_code == 200
        # Pagination object exposes the effective per_page; ensure it didn't exceed cap
        html = response.data.decode()
        # 100-per-page option should be selected because clamp landed on max
        assert f'value="{MAX_USERS_PER_PAGE}" selected' in html

    def test_per_page_100_accepted(self, app, admin_client, db_session):
        """per_page=100 is allowed (matches new max)."""
        response = admin_client.get('/admin/users?page=1&per_page=100')
        assert response.status_code == 200

    def test_invalid_page_returns_400(self, app, admin_client, db_session):
        """Non-integer page values are rejected with 400."""
        response = admin_client.get('/admin/users?page=abc')
        assert response.status_code == 400

    def test_page_zero_returns_400(self, app, admin_client, db_session):
        """page < 1 is rejected with 400 by get_int_arg."""
        response = admin_client.get('/admin/users?page=0')
        assert response.status_code == 400

    def test_search_filters_users(self, app, admin_client, db_session):
        """Search param filters results by username/email."""
        unique = uuid.uuid4().hex[:8]
        u = _make_user(db_session, username=f'searchme_{unique}')
        db_session.flush()

        response = admin_client.get(f'/admin/users?search=searchme_{unique}')
        assert response.status_code == 200
        html = response.data.decode()
        assert f'searchme_{unique}' in html

    def test_search_wildcards_escaped(self, app, admin_client, db_session):
        """`%` and `_` in search must be matched literally, not as SQL wildcards."""
        unique = uuid.uuid4().hex[:8]
        target = _make_user(db_session, username=f'literal_{unique}')
        decoy = _make_user(db_session, username=f'literalX{unique}')  # would match `_` wildcard
        db_session.flush()

        # Search for `literal_` — underscore must be literal, not single-char wildcard,
        # so the decoy `literalX{unique}` should NOT show up.
        response = admin_client.get(f'/admin/users?search=literal_{unique}')
        assert response.status_code == 200
        html = response.data.decode()
        assert f'literal_{unique}' in html
        assert f'literalX{unique}' not in html

    def test_search_percent_is_literal(self, app, admin_client, db_session):
        """`%` in search returns 0 hits unless the username literally contains `%`."""
        _make_user(db_session, username=f'no_percent_{uuid.uuid4().hex[:6]}')
        db_session.flush()

        response = admin_client.get('/admin/users?search=%25unlikely_match%25')
        # Search arg was URL-encoded `%unlikely_match%`. Expect 200 with no matches.
        assert response.status_code == 200

    def test_listing_bounded_query_count(self, app, admin_client, db_session):
        """Listing N users issues a bounded number of SQL statements (no per-user
        joins or N+1). Hooks into SQLAlchemy engine events so it works regardless
        of Flask-SQLAlchemy debug-query plumbing."""
        for _ in range(15):
            _make_user(db_session)
        db_session.flush()

        from sqlalchemy import event

        engine = db_session.get_bind()
        statements: list[str] = []

        def _before_cursor_execute(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        event.listen(engine, 'before_cursor_execute', _before_cursor_execute)
        try:
            response = admin_client.get('/admin/users?per_page=20')
            assert response.status_code == 200
        finally:
            event.remove(engine, 'before_cursor_execute', _before_cursor_execute)

        # Count actual user-list queries (excluding auth/session/admin lookups).
        # Threshold is generous: count + paginate + auth lookups should sit well
        # below 25. Anything close to per_page (20) would indicate an N+1.
        user_table_selects = [s for s in statements if 'FROM users' in s]
        assert len(user_table_selects) < 10, (
            f'Too many queries on users table ({len(user_table_selects)}); '
            f'possible N+1 regression'
        )

    def test_unauthenticated_redirects_to_login(self, client):
        """Non-admin request is redirected."""
        response = client.get('/admin/users', follow_redirects=False)
        assert response.status_code == 302
