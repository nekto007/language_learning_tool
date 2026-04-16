# app/admin/audit.py

"""Admin audit log: records destructive admin actions for accountability."""

import logging
from datetime import datetime, UTC
from typing import Optional

from app.utils.db import db

logger = logging.getLogger(__name__)


class AdminAuditLog(db.Model):
    """Records admin mutations so every destructive action is traceable."""

    __tablename__ = 'admin_audit_log'

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    action = db.Column(db.String(128), nullable=False)
    target_type = db.Column(db.String(64), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    def __repr__(self) -> str:
        return f'<AdminAuditLog id={self.id} admin={self.admin_id} action={self.action}>'


def log_admin_action(
    admin_id: int,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
) -> None:
    """Persist an audit log entry for a destructive admin action.

    Failures are swallowed so the primary operation is never blocked.
    """
    try:
        nested = db.session.begin_nested()
        entry = AdminAuditLog(
            admin_id=admin_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
        )
        db.session.add(entry)
        db.session.flush()
        nested.commit()
    except Exception:
        nested.rollback()
        logger.exception('Failed to write admin audit log entry: action=%s', action)
