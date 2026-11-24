"""Immutable private item banks and account-owned placement attempts."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.utils.db import db


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PlacementBank(db.Model):
    __tablename__ = 'placement_banks'
    id = db.Column(db.String(64), primary_key=True)
    label = db.Column(db.String(120), nullable=False)
    content = db.Column(db.JSON, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class PlacementAttempt(db.Model):
    __tablename__ = 'placement_attempts'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    bank_id = db.Column(db.String(64), db.ForeignKey('placement_banks.id'), nullable=False)
    mode = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False, default='active')
    state = db.Column(db.JSON, nullable=False, default=dict)
    result = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    applied_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (
        db.Index('uq_placement_attempt_active_user', 'user_id', unique=True,
                 postgresql_where=db.text("status = 'active'"), sqlite_where=db.text("status = 'active'")),
    )
