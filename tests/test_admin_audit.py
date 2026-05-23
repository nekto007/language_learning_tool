"""
Tests for admin audit log — audit_routes and _get_audit_entries helper.
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _get_audit_entries unit tests (no DB required)
# ---------------------------------------------------------------------------

class TestGetAuditEntries:
    """Unit tests for _get_audit_entries with mocked DB session."""

    def _make_log(self, id=1, admin_id=10, action='delete_user', target_type='User', target_id=5):
        log = MagicMock()
        log.id = id
        log.admin_id = admin_id
        log.action = action
        log.target_type = target_type
        log.target_id = target_id
        log.created_at = datetime(2026, 5, 20, 12, 0, 0)
        return log

    def _make_user(self, email='admin@example.com'):
        u = MagicMock()
        u.email = email
        return u

    def _make_db_session(self, rows):
        db_session = MagicMock()
        mock_query = MagicMock()
        mock_query.outerjoin.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_offset = MagicMock()
        mock_offset.all.return_value = rows
        mock_query.offset.return_value = mock_offset
        db_session.query.return_value = mock_query
        return db_session

    def test_empty_returns_no_entries(self):
        from app.admin.routes.audit_routes import _get_audit_entries

        db_session = self._make_db_session([])
        entries, has_more = _get_audit_entries(db_session, limit=50, offset=0)
        assert entries == []
        assert has_more is False

    def test_has_more_when_extra_row(self):
        from app.admin.routes.audit_routes import _get_audit_entries

        rows = [(self._make_log(id=i), self._make_user()) for i in range(51)]
        db_session = self._make_db_session(rows)
        entries, has_more = _get_audit_entries(db_session, limit=50, offset=0)
        assert len(entries) == 50
        assert has_more is True

    def test_no_has_more_exact_limit(self):
        from app.admin.routes.audit_routes import _get_audit_entries

        rows = [(self._make_log(id=i), self._make_user()) for i in range(50)]
        db_session = self._make_db_session(rows)
        entries, has_more = _get_audit_entries(db_session, limit=50, offset=0)
        assert len(entries) == 50
        assert has_more is False

    def test_entry_fields_populated(self):
        from app.admin.routes.audit_routes import _get_audit_entries

        log = self._make_log(id=7, admin_id=99, action='ban_user', target_type='User', target_id=42)
        user = self._make_user(email='superadmin@example.com')
        db_session = self._make_db_session([(log, user)])
        entries, _ = _get_audit_entries(db_session, limit=50, offset=0)

        assert len(entries) == 1
        e = entries[0]
        assert e['id'] == 7
        assert e['admin_id'] == 99
        assert e['admin_email'] == 'superadmin@example.com'
        assert e['action'] == 'ban_user'
        assert e['target_type'] == 'User'
        assert e['target_id'] == 42

    def test_deleted_admin_shows_placeholder(self):
        from app.admin.routes.audit_routes import _get_audit_entries

        log = self._make_log()
        db_session = self._make_db_session([(log, None)])
        entries, _ = _get_audit_entries(db_session, limit=50, offset=0)
        assert entries[0]['admin_email'] == '(deleted)'


# ---------------------------------------------------------------------------
# audit_routes integration tests (require Flask app + mock admin)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_admin_user():
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.is_admin = True
    mock_user.id = 999
    mock_user.username = 'mock_admin'
    with patch('app.admin.utils.decorators.current_user', mock_user), \
         patch('flask_login.utils.current_user', mock_user):
        yield mock_user


def _fake_entry(action='delete_user', admin_email='admin@test.com'):
    return {
        'id': 1,
        'timestamp': datetime(2026, 5, 20, 12, 0, 0),
        'admin_id': 1,
        'admin_email': admin_email,
        'action': action,
        'target_type': 'User',
        'target_id': 5,
    }


class TestAuditRoutes:
    """Integration tests for /admin/audit-log routes."""

    def test_audit_log_requires_admin(self, client):
        response = client.get('/admin/audit-log', follow_redirects=False)
        assert response.status_code in (302, 401)

    def test_audit_log_renders_for_admin(self, client, mock_admin_user):
        fake_entries = [_fake_entry()]
        with patch('app.admin.routes.audit_routes._get_audit_entries', return_value=(fake_entries, False)), \
             patch('app.admin.routes.audit_routes.db') as mock_db:
            mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
            response = client.get('/admin/audit-log')

        assert response.status_code == 200
        body = response.data.decode()
        assert 'delete_user' in body
        assert 'admin@test.com' in body

    def test_audit_log_empty_shows_placeholder(self, client, mock_admin_user):
        with patch('app.admin.routes.audit_routes._get_audit_entries', return_value=([], False)), \
             patch('app.admin.routes.audit_routes.db') as mock_db:
            mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
            response = client.get('/admin/audit-log')

        assert response.status_code == 200
        body = response.data.decode()
        assert 'Нет записей' in body

    def test_audit_log_pagination_has_more(self, client, mock_admin_user):
        fake_entries = [_fake_entry(action=f'action_{i}') for i in range(50)]
        with patch('app.admin.routes.audit_routes._get_audit_entries', return_value=(fake_entries, True)), \
             patch('app.admin.routes.audit_routes.db') as mock_db:
            mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
            response = client.get('/admin/audit-log')

        assert response.status_code == 200
        body = response.data.decode()
        assert 'Вперёд' in body

    def test_audit_log_filter_action_passed(self, client, mock_admin_user):
        with patch('app.admin.routes.audit_routes._get_audit_entries', return_value=([], False)) as mock_fn, \
             patch('app.admin.routes.audit_routes.db') as mock_db:
            mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
            client.get('/admin/audit-log?action=delete')

        call_kwargs = mock_fn.call_args[1]
        assert call_kwargs.get('action_filter') == 'delete'

    def test_audit_log_filter_date_parsed(self, client, mock_admin_user):
        with patch('app.admin.routes.audit_routes._get_audit_entries', return_value=([], False)) as mock_fn, \
             patch('app.admin.routes.audit_routes.db') as mock_db:
            mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
            client.get('/admin/audit-log?date_from=2026-05-01&date_to=2026-05-31')

        call_kwargs = mock_fn.call_args[1]
        assert call_kwargs.get('date_from') == datetime(2026, 5, 1)
        assert call_kwargs.get('date_to') == datetime(2026, 5, 31)

    def test_audit_log_filter_invalid_admin_id_ignored(self, client, mock_admin_user):
        with patch('app.admin.routes.audit_routes._get_audit_entries', return_value=([], False)) as mock_fn, \
             patch('app.admin.routes.audit_routes.db') as mock_db:
            mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
            response = client.get('/admin/audit-log?admin_id=notanumber')

        assert response.status_code == 200
        call_kwargs = mock_fn.call_args[1]
        assert call_kwargs.get('admin_id') is None
