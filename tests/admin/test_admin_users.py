"""Tests for admin user management security: self-deactivation prevention,
audit logging for is_admin changes, admin_required protection, and CSV sanitization."""
import csv
import io
import uuid

import pytest

from app.admin.audit import AdminAuditLog
from app.admin.services.user_management_service import UserManagementService
from app.admin.utils.export_helpers import _sanitize_csv_cell
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
    u.set_password('testpass123')
    db_session.add(u)
    db_session.flush()
    return u


class TestAdminRequiredProtection:
    """Verify user management routes reject anonymous and non-admin requests."""

    @pytest.mark.smoke
    def test_users_list_rejects_anonymous(self, client):
        resp = client.get('/admin/users', follow_redirects=False)
        assert resp.status_code in (302, 401, 403)

    def test_toggle_status_rejects_anonymous(self, client):
        resp = client.post('/admin/users/1/toggle_status', follow_redirects=False)
        assert resp.status_code in (302, 401, 403)

    def test_toggle_admin_rejects_anonymous(self, client):
        resp = client.post('/admin/users/1/toggle_admin', follow_redirects=False)
        assert resp.status_code in (302, 401, 403)

    def test_export_rejects_anonymous(self, client):
        resp = client.get('/admin/users/export', follow_redirects=False)
        assert resp.status_code in (302, 401, 403)


class TestSelfDeactivationPrevention:
    """Admin must not be able to deactivate their own account."""

    @pytest.mark.smoke
    def test_route_blocks_self_deactivation(self, app, db_session, admin_client, admin_user):
        """POST /admin/users/<id>/toggle_status with own id should flash error and not deactivate."""
        resp = admin_client.post(
            f'/admin/users/{admin_user.id}/toggle_status',
            follow_redirects=False,
        )
        assert resp.status_code == 302

        db_session.refresh(admin_user)
        assert admin_user.active is True

    def test_route_allows_deactivating_other_user(self, app, db_session, admin_client, admin_user):
        """Admin can deactivate a different user."""
        other = _make_user(db_session, active=True)
        db_session.commit()

        resp = admin_client.post(
            f'/admin/users/{other.id}/toggle_status',
            follow_redirects=False,
        )
        assert resp.status_code == 302

        db_session.refresh(other)
        assert other.active is False

    def test_service_allows_self_deactivation(self, app, db_session):
        """Service has no self-deactivation guard — protection is at route layer."""
        user = _make_user(db_session, active=True)
        db_session.commit()

        result = UserManagementService.toggle_user_status(user.id)
        assert result is not None
        assert result['active'] is False


class TestAdminStatusAuditLogging:
    """is_admin changes must be recorded in AdminAuditLog."""

    @pytest.mark.smoke
    def test_toggle_admin_grant_logs_audit(self, app, db_session, admin_client, admin_user):
        """Granting admin logs user.grant_admin in AdminAuditLog."""
        target = _make_user(db_session, is_admin=False)
        db_session.commit()

        admin_client.post(
            f'/admin/users/{target.id}/toggle_admin',
            follow_redirects=False,
        )

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin_user.id,
            action='user.grant_admin',
            target_id=target.id,
        ).first()
        assert entry is not None

    def test_toggle_admin_revoke_logs_audit(self, app, db_session, admin_client, admin_user):
        """Revoking admin logs user.revoke_admin in AdminAuditLog."""
        target = _make_user(db_session, is_admin=True)
        db_session.commit()

        admin_client.post(
            f'/admin/users/{target.id}/toggle_admin',
            follow_redirects=False,
        )

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin_user.id,
            action='user.revoke_admin',
            target_id=target.id,
        ).first()
        assert entry is not None

    def test_toggle_admin_self_blocked(self, app, db_session, admin_client, admin_user):
        """Admin cannot modify their own admin status — no audit entry created."""
        before_count = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin_user.id,
            action='user.grant_admin',
            target_id=admin_user.id,
        ).count()

        admin_client.post(
            f'/admin/users/{admin_user.id}/toggle_admin',
            follow_redirects=False,
        )

        after_count = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin_user.id,
            action='user.grant_admin',
            target_id=admin_user.id,
        ).count()
        assert after_count == before_count

    def test_status_toggle_logs_activate(self, app, db_session, admin_client, admin_user):
        """Activating a user logs user.activate in AdminAuditLog."""
        target = _make_user(db_session, active=False)
        db_session.commit()

        admin_client.post(
            f'/admin/users/{target.id}/toggle_status',
            follow_redirects=False,
        )

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin_user.id,
            action='user.activate',
            target_id=target.id,
        ).first()
        assert entry is not None

    def test_status_toggle_logs_deactivate(self, app, db_session, admin_client, admin_user):
        """Deactivating a user logs user.deactivate in AdminAuditLog."""
        target = _make_user(db_session, active=True)
        db_session.commit()

        admin_client.post(
            f'/admin/users/{target.id}/toggle_status',
            follow_redirects=False,
        )

        entry = db_session.query(AdminAuditLog).filter_by(
            admin_id=admin_user.id,
            action='user.deactivate',
            target_id=target.id,
        ).first()
        assert entry is not None


class TestCsvExportSanitization:
    """CSV export must sanitize cell values to prevent formula injection."""

    @pytest.mark.smoke
    def test_export_returns_csv_content_type(self, app, db_session, admin_client):
        resp = admin_client.get('/admin/users/export')
        assert resp.status_code == 200
        assert 'text/csv' in resp.content_type

    def test_sanitize_csv_cell_strips_formula_prefix(self):
        """_sanitize_csv_cell must neutralize formula-injection characters."""
        for dangerous in ['=CMD', '+cmd', '-cmd', '@SUM']:
            result = _sanitize_csv_cell(dangerous)
            assert not result.startswith(('=', '+', '-', '@')), (
                f"_sanitize_csv_cell({dangerous!r}) -> {result!r} still starts with dangerous char"
            )

    def test_sanitize_csv_cell_preserves_normal_values(self):
        assert _sanitize_csv_cell('john') == 'john'
        assert _sanitize_csv_cell('2024-01-01') == '2024-01-01'
        assert _sanitize_csv_cell(42) == '42'
        assert _sanitize_csv_cell(None) == ''

    def test_export_csv_does_not_include_password_hash(self, app, db_session, admin_client):
        """Exported CSV must not contain hashed passwords."""
        user = _make_user(db_session)
        db_session.commit()

        resp = admin_client.get('/admin/users/export')
        content = resp.data.decode('utf-8')
        assert 'password' not in content.lower() or 'password_hash' not in content
        assert 'pbkdf2' not in content
        assert '$2b$' not in content

    def test_export_csv_rows_are_sanitized(self, app, db_session, admin_client):
        """CSV rows must not contain formula-injection sequences."""
        user = _make_user(db_session, username='=FORMULA_USER')
        db_session.commit()

        resp = admin_client.get('/admin/users/export')
        content = resp.data.decode('utf-8')
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            for val in row.values():
                assert not val.startswith(('=', '+', '@')), (
                    f"Unsanitized CSV value: {val!r}"
                )


class TestToggleAdminServiceLayer:
    """Unit-level tests for UserManagementService toggle methods."""

    def test_toggle_admin_prevents_self_modification(self, app, db_session):
        user = _make_user(db_session, is_admin=True)
        db_session.commit()

        success, msg = UserManagementService.toggle_admin_status(user.id, user.id)
        assert success is False
        assert 'Cannot modify your own admin status' in msg

    def test_toggle_admin_user_not_found(self, app, db_session):
        success, msg = UserManagementService.toggle_admin_status(999999, 1)
        assert success is False
        assert 'not found' in msg.lower()

    def test_toggle_user_status_not_found(self, app, db_session):
        result = UserManagementService.toggle_user_status(999999)
        assert result is None
