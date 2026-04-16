"""Tests for admin audit log (task 34)."""
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

        # Create a user to delete
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
            action='delete_user',
            target_type='User',
            target_id=target_id,
        ).first()

        assert entry is not None
