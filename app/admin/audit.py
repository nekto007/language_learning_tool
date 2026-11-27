# app/admin/audit.py

"""Admin audit log: records destructive admin actions for accountability."""

import logging
from datetime import UTC, datetime
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


class ChapterEditAudit(db.Model):
    """Revision and location metadata for one chapter edit."""

    __tablename__ = 'admin_chapter_edit_audit'

    audit_id = db.Column(db.Integer, db.ForeignKey('admin_audit_log.id', ondelete='CASCADE'), primary_key=True)
    book_id = db.Column(db.Integer, nullable=False)
    chapter_number = db.Column(db.Integer, nullable=False)
    chapter_title = db.Column(db.String(255), nullable=False)
    revision_before = db.Column(db.String(64), nullable=False)
    revision_after = db.Column(db.String(64), nullable=False)
    generation_before = db.Column(db.BigInteger, nullable=False)
    generation_after = db.Column(db.BigInteger, nullable=False)
    paragraph = db.Column(db.Integer, nullable=True)


def log_admin_action(
    admin_id: int,
    action: str,
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    *, required: bool = False,
) -> int | None:
    """Stage an audit log entry and return its ID if staged successfully.

    The entry is added to the current session inside a SAVEPOINT so that
    a write failure does not poison the caller's transaction. The caller
    is responsible for committing the surrounding transaction — the entry
    becomes durable together with the mutation it documents (or rolls
    back with it). Failures while staging are swallowed so the primary
    operation is never blocked unless its caller explicitly requires an audit.
    """
    nested = None
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
        entry_id = entry.id
        nested.commit()
        return entry_id
    except Exception:
        if nested is not None:
            try:
                nested.rollback()
            except Exception:
                pass
        logger.exception('Failed to write admin audit log entry: action=%s', action)
        if required:
            raise
        return None
