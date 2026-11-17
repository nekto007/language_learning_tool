"""Opt-in mobile reminders and durable, per-user delivery claims."""
from datetime import datetime

from app.utils.db import db


class PushPreference(db.Model):
    __tablename__ = 'native_push_preferences'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    hours = db.Column(db.JSON, nullable=False, default=lambda: [9, 15, 20])


class PushDevice(db.Model):
    __tablename__ = 'native_push_devices'
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    secret_hash = db.Column(db.String(64), nullable=False)
    token = db.Column(db.String(512), nullable=False)
    environment = db.Column(db.String(16), nullable=False)
    auth_version = db.Column(db.String(64), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('token', 'environment', name='uq_native_push_token_environment'),)


class PushDelivery(db.Model):
    __tablename__ = 'native_push_deliveries'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    study_date = db.Column(db.Date, nullable=False)
    slot = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    accepted = db.Column(db.Integer, nullable=False, default=0)
    __table_args__ = (db.UniqueConstraint('user_id', 'study_date', 'slot', name='uq_native_push_user_day_slot'),)
