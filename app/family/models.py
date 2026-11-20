from datetime import datetime, timezone, UTC
from uuid import uuid4

from app.utils.db import db


class FamilyLink(db.Model):
    __tablename__ = "family_links"
    id = db.Column(db.String(32), primary_key=True, default=lambda: uuid4().hex)
    parent_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    child_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    parent_version = db.Column(db.String(128), nullable=False)
    child_version = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(UTC))
    __table_args__ = (db.CheckConstraint("parent_id <> child_id", name="ck_family_different_users"),)


class FamilyInvitation(db.Model):
    __tablename__ = "family_invitations"
    code_hash = db.Column(db.String(64), primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    child_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_version = db.Column(db.String(128), nullable=False)
    child_version = db.Column(db.String(128), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    accepted_at = db.Column(db.DateTime)
