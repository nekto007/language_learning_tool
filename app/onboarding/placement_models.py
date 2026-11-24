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
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)
    guest_key = db.Column(db.String(64), db.ForeignKey('placement_guests.key', ondelete='CASCADE'), nullable=True, index=True)
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
        db.CheckConstraint('(user_id IS NOT NULL) <> (guest_key IS NOT NULL)', name='ck_placement_attempt_owner'),
        db.Index('uq_placement_attempt_active_guest', 'guest_key', unique=True,
                 postgresql_where=db.text("status = 'active'"), sqlite_where=db.text("status = 'active'")),
        db.Index('uq_placement_attempt_active_user', 'user_id', unique=True,
                 postgresql_where=db.text("status = 'active'"), sqlite_where=db.text("status = 'active'")),
    )


class PlacementGuest(db.Model):
    __tablename__ = 'placement_guests'
    key = db.Column(db.String(64), primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)


class PlacementPreference(db.Model):
    __tablename__ = 'placement_preferences'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    dismissed_key = db.Column(db.String(100), nullable=True)
    dismissed_keys = db.Column(db.JSON, nullable=False, default=list)
    dismissed_at = db.Column(db.DateTime, nullable=True)
    level_checkpoints = db.Column(db.JSON, nullable=False, default=dict)


class PlacementReview(db.Model):
    __tablename__ = 'placement_reviews'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    attempt_id = db.Column(db.String(36), db.ForeignKey('placement_attempts.id', ondelete='CASCADE'), nullable=False)
    topic_slug = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(16), nullable=False, default='candidate')
    due_on = db.Column(db.Date, nullable=False)
    completed_on = db.Column(db.Date, nullable=True)
    practice = db.Column(db.JSON, nullable=False, default=dict)
    __table_args__ = (db.UniqueConstraint('attempt_id', 'topic_slug', name='uq_placement_review_attempt_topic'),)
