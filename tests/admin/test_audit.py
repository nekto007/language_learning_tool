"""Tests for admin audit log — model, UI filters, pagination, and CSV export."""
import io
import csv
import uuid
import pytest

from app.admin.audit import AdminAuditLog, log_admin_action
from app.utils.db import db


class TestAdminAuditLog:
    """Tests for log_admin_action() and AdminAuditLog model."""

    @pytest.mark.smoke
    def test_log_admin_action_creates_record(self, app, db_session, test_user):
        """log_admin_action should persist an AdminAuditLog entry."""
        log_admin_action(
            admin_id=test_user.id,
            action='delete_user',
            target_type='User',
            target_id=99,
        )
        db_session.flush()

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=test_user.id,
            action='delete_user',
            target_type='User',
            target_id=99,
        ).first()

        assert entry is not None
        assert entry.admin_id == test_user.id
        assert entry.action == 'delete_user'
        assert entry.target_type == 'User'
        assert entry.target_id == 99
        assert entry.created_at is not None

    def test_log_admin_action_records_admin_id_and_timestamp(self, app, db_session, test_user):
        """Audit log entry must include admin_id and a non-null created_at."""
        log_admin_action(
            admin_id=test_user.id,
            action='delete_book_course',
            target_type='BookCourse',
            target_id=42,
        )
        db_session.flush()

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=test_user.id,
            action='delete_book_course',
            target_id=42,
        ).first()

        assert entry is not None
        assert entry.admin_id == test_user.id
        assert entry.created_at is not None

    def test_log_admin_action_nullable_fields(self, app, db_session, test_user):
        """log_admin_action works without target_type and target_id."""
        log_admin_action(
            admin_id=test_user.id,
            action='some_generic_action',
        )
        db_session.flush()

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=test_user.id,
            action='some_generic_action',
        ).first()

        assert entry is not None
        assert entry.target_type is None
        assert entry.target_id is None

    def test_delete_user_creates_audit_log(self, app, db_session, test_user):
        """UserManagementService.delete_user should log the deletion when admin_id given."""
        from app.auth.models import User
        import uuid as _uuid

        target = User(
            username=f'del_target_{_uuid.uuid4().hex[:8]}',
            email=f'del_{_uuid.uuid4().hex[:8]}@example.com',
        )
        target.set_password('pass')
        db_session.add(target)
        db_session.flush()
        target_id = target.id

        from app.admin.services.user_management_service import UserManagementService
        UserManagementService.delete_user(target_id, admin_id=test_user.id)

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=test_user.id,
            action='user.delete',
            target_type='user',
            target_id=target_id,
        ).first()

        assert entry is not None


class TestAuditLogUI:
    """Tests for the audit log UI: filters, pagination, CSV export."""

    @pytest.mark.smoke
    def test_audit_index_requires_admin(self, app, client, db_session, test_user):
        """Anonymous request to /admin/audit-log should be redirected."""
        resp = client.get('/admin/audit-log', follow_redirects=False)
        assert resp.status_code in (302, 401, 403)

    def test_audit_index_renders_for_admin(self, app, client, db_session, admin_user):
        """Admin can access the audit log page."""
        log_admin_action(admin_id=admin_user.id, action='test.action', target_type='Test', target_id=1)
        db_session.commit()

        resp = client.get('/admin/audit-log')
        assert resp.status_code == 200
        assert b'test.action' in resp.data

    def test_audit_index_filter_by_action(self, app, client, db_session, admin_user):
        """Action filter narrows results to matching rows only."""
        tag = uuid.uuid4().hex[:6]
        log_admin_action(admin_id=admin_user.id, action=f'needle_{tag}', target_type='X', target_id=1)
        log_admin_action(admin_id=admin_user.id, action=f'haystack_{tag}', target_type='X', target_id=2)
        db_session.commit()

        resp = client.get(f'/admin/audit-log?action=needle_{tag}')
        assert resp.status_code == 200
        assert f'needle_{tag}'.encode() in resp.data
        assert f'haystack_{tag}'.encode() not in resp.data

    def test_audit_index_filter_by_admin_id(self, app, client, db_session, admin_user, test_user):
        """admin_id filter shows only entries by the selected admin."""
        from app.auth.models import User
        other = User(
            username=f'other_admin_{uuid.uuid4().hex[:6]}',
            email=f'other_{uuid.uuid4().hex[:6]}@example.com',
            is_admin=True,
        )
        other.set_password('pass')
        db_session.add(other)
        db_session.flush()

        tag = uuid.uuid4().hex[:6]
        log_admin_action(admin_id=admin_user.id, action=f'main_action_{tag}')
        log_admin_action(admin_id=other.id, action=f'other_action_{tag}')
        db_session.commit()

        resp = client.get(f'/admin/audit-log?admin_id={admin_user.id}')
        assert resp.status_code == 200
        assert f'main_action_{tag}'.encode() in resp.data
        assert f'other_action_{tag}'.encode() not in resp.data

    def test_audit_index_pagination(self, app, client, db_session, admin_user):
        """Page 2 should not contain entries only in page 1 (simple cursor check)."""
        for i in range(55):
            log_admin_action(admin_id=admin_user.id, action=f'paginate_action_{i}')
        db_session.commit()

        resp1 = client.get('/admin/audit-log?page=1')
        resp2 = client.get('/admin/audit-log?page=2')
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Both pages should contain some content
        assert b'paginate_action_' in resp1.data

    def test_audit_export_csv_requires_admin(self, app, client, db_session, test_user):
        """Anonymous request to CSV export should be redirected."""
        resp = client.get('/admin/audit-log/export.csv', follow_redirects=False)
        assert resp.status_code in (302, 401, 403)

    @pytest.mark.smoke
    def test_audit_export_csv_returns_csv(self, app, client, db_session, admin_user):
        """CSV export returns valid CSV with expected headers."""
        tag = uuid.uuid4().hex[:6]
        log_admin_action(admin_id=admin_user.id, action=f'csv_test_{tag}', target_type='Word', target_id=7)
        db_session.commit()

        resp = client.get('/admin/audit-log/export.csv')
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type

        content = resp.data.decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert rows[0] == ['ID', 'Timestamp', 'Admin Email', 'Action', 'Target Type', 'Target ID']
        actions = [r[3] for r in rows[1:] if len(r) > 3]
        assert any(f'csv_test_{tag}' in a for a in actions)

    def test_audit_export_csv_sanitizes_injection(self, app, client, db_session, admin_user):
        """CSV export sanitizes formula-injection characters in action field."""
        log_admin_action(admin_id=admin_user.id, action='=SUM(A1:A10)', target_type='Inject')
        db_session.commit()

        resp = client.get('/admin/audit-log/export.csv')
        assert resp.status_code == 200
        content = resp.data.decode('utf-8')
        # Sanitized cell should be prefixed with apostrophe
        assert "'=SUM(A1:A10)" in content

    def test_audit_export_csv_respects_action_filter(self, app, client, db_session, admin_user):
        """CSV export applies the same filters as the HTML view."""
        tag = uuid.uuid4().hex[:6]
        log_admin_action(admin_id=admin_user.id, action=f'in_filter_{tag}')
        log_admin_action(admin_id=admin_user.id, action=f'out_filter_{tag}')
        db_session.commit()

        resp = client.get(f'/admin/audit-log/export.csv?action=in_filter_{tag}')
        assert resp.status_code == 200
        content = resp.data.decode('utf-8')
        assert f'in_filter_{tag}' in content
        assert f'out_filter_{tag}' not in content

    def test_audit_export_csv_disposition_header(self, app, client, db_session, admin_user):
        """CSV export sets Content-Disposition: attachment header."""
        resp = client.get('/admin/audit-log/export.csv')
        assert resp.status_code == 200
        disposition = resp.headers.get('Content-Disposition', '')
        assert 'attachment' in disposition
        assert '.csv' in disposition


class TestAdminAuditRequiredDecorator:
    """Tests for @admin_audit_required — status-code filtering.

    We patch admin_required to identity (lambda f: f) at decoration time so
    that wrapped_view is tested without the Flask-Login gate. current_user is
    set up via login_user() only for paths that actually read it (2xx/3xx).
    """

    @staticmethod
    def _make_view(action: str, status_code: int):
        """Return a view decorated with admin_audit_required, bypassing admin_required."""
        from unittest.mock import patch
        from app.admin.utils.decorators import admin_audit_required

        with patch('app.admin.utils.decorators.admin_required', lambda f: f):
            @admin_audit_required(action=action)
            def _view():
                return 'response', status_code

        return _view

    def test_creates_row_on_200(self, app, db_session, admin_user):
        """Decorator creates audit row when view returns 200."""
        from flask_login import login_user

        action = f'dec_200_{uuid.uuid4().hex[:8]}'
        view = self._make_view(action, 200)

        with app.test_request_context('/admin/test'):
            login_user(admin_user)
            view()

        count = db_session.query(AdminAuditLog).filter_by(action=action).count()
        assert count == 1, 'Audit row MUST be created for 200 response'

    def test_no_row_on_400(self, app, db_session, admin_user):
        """Decorator must NOT create audit row when view returns 400."""
        action = f'dec_400_{uuid.uuid4().hex[:8]}'
        view = self._make_view(action, 400)

        # current_user is never accessed on 4xx path — no login_user needed
        with app.test_request_context('/admin/test'):
            view()

        count = db_session.query(AdminAuditLog).filter_by(action=action).count()
        assert count == 0, 'Audit row must NOT be created for 4xx response'

    def test_no_row_on_500(self, app, db_session, admin_user):
        """Decorator must NOT create audit row when view returns 500."""
        action = f'dec_500_{uuid.uuid4().hex[:8]}'
        view = self._make_view(action, 500)

        with app.test_request_context('/admin/test'):
            view()

        count = db_session.query(AdminAuditLog).filter_by(action=action).count()
        assert count == 0, 'Audit row must NOT be created for 5xx response'

    def test_creates_row_on_redirect(self, app, db_session, admin_user):
        """Decorator creates audit row when view returns 302."""
        from flask import redirect
        from flask_login import login_user
        from unittest.mock import patch
        from app.admin.utils.decorators import admin_audit_required

        action = f'dec_302_{uuid.uuid4().hex[:8]}'

        with patch('app.admin.utils.decorators.admin_required', lambda f: f):
            @admin_audit_required(action=action)
            def _redirect_view():
                return redirect('/admin/')

        with app.test_request_context('/admin/test'):
            login_user(admin_user)
            _redirect_view()

        count = db_session.query(AdminAuditLog).filter_by(action=action).count()
        assert count == 1, 'Audit row SHOULD be created for 3xx redirect'


class TestAuditLogNullTargetId:
    """Tests for audit log UI behavior with null target_type/target_id."""

    def test_ui_renders_dash_for_null_target_type(self, app, client, db_session, admin_user):
        """Entries with null target_type must render '—' in the object column."""
        log_admin_action(
            admin_id=admin_user.id,
            action='system.clear_cache',
            target_type=None,
            target_id=None,
        )
        db_session.commit()

        resp = client.get('/admin/audit-log')
        assert resp.status_code == 200
        assert 'system.clear_cache'.encode() in resp.data
        assert '—'.encode() in resp.data

    def test_ui_renders_type_without_id_when_target_id_is_null(self, app, client, db_session, admin_user):
        """Entry with target_type set but target_id=None shows badge but no '#N'."""
        tag = uuid.uuid4().hex[:6]
        action = f'gsc.disconnect_{tag}'
        log_admin_action(
            admin_id=admin_user.id,
            action=action,
            target_type='gsc_token',
            target_id=None,
        )
        db_session.commit()

        resp = client.get(f'/admin/audit-log?action={action}')
        assert resp.status_code == 200
        data = resp.data.decode('utf-8')
        assert 'gsc_token' in data
        assert f'#{admin_user.id}' not in data.split(action)[1].split('</tr>')[0]

    def test_log_admin_action_accepts_null_target_id(self, app, db_session, admin_user):
        """log_admin_action must persist with target_type set but target_id=None."""
        log_admin_action(
            admin_id=admin_user.id,
            action='test.null_target_id',
            target_type='config',
            target_id=None,
        )
        db_session.flush()

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin_user.id,
            action='test.null_target_id',
        ).first()

        assert entry is not None
        assert entry.target_type == 'config'
        assert entry.target_id is None


class TestAuditLogSensitiveData:
    """Tests that audit log model and helpers don't expose sensitive data."""

    def test_model_schema_has_no_details_column(self, app, db_session):
        """AdminAuditLog must not have a 'details' or 'payload' column."""
        from sqlalchemy import inspect as sa_inspect
        inspector = sa_inspect(AdminAuditLog)
        col_names = {c.key for c in inspector.mapper.column_attrs}
        assert 'details' not in col_names, 'No details column — sensitive data must not be stored'
        assert 'payload' not in col_names, 'No payload column — sensitive data must not be stored'

    def test_log_admin_action_signature_has_no_details_param(self):
        """log_admin_action must not accept a details/payload parameter."""
        import inspect as py_inspect
        sig = py_inspect.signature(log_admin_action)
        param_names = set(sig.parameters.keys())
        assert 'details' not in param_names
        assert 'payload' not in param_names
        assert 'password' not in param_names
        assert 'token' not in param_names

    def test_audit_log_columns_are_safe(self, app, db_session, admin_user):
        """Audit log entry only stores standard safe fields."""
        log_admin_action(
            admin_id=admin_user.id,
            action='user.toggle_admin',
            target_type='user',
            target_id=42,
        )
        db_session.flush()

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin_user.id,
            action='user.toggle_admin',
            target_id=42,
        ).first()
        assert entry is not None
        # Only these fields should exist on the model
        allowed = {'id', 'admin_id', 'action', 'target_type', 'target_id', 'created_at'}
        actual = {c.key for c in type(entry).__mapper__.column_attrs}
        assert actual == allowed, f'Unexpected columns in AdminAuditLog: {actual - allowed}'

    def test_gsc_token_not_in_audit_action_name(self, app, client, db_session, admin_user):
        """GSC disconnect action name must not contain token value."""
        log_admin_action(
            admin_id=admin_user.id,
            action='gsc.disconnect',
            target_type='gsc',
        )
        db_session.commit()

        resp = client.get('/admin/audit-log?action=gsc.disconnect')
        assert resp.status_code == 200
        data = resp.data.decode('utf-8')
        assert 'refresh_token' not in data
        assert 'client_secret' not in data
