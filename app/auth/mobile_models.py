"""Private, expiring native authentication proofs. Never store raw passwords or codes."""

from datetime import datetime, timezone
from app.utils.db import db


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class MobileAuthChallenge(db.Model):
    __tablename__ = "mobile_auth_challenges"
    id = db.Column(db.String(64), primary_key=True)
    kind = db.Column(db.String(24), nullable=False)
    email = db.Column(db.String(120), nullable=True, index=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    payload = db.Column(db.JSON, nullable=False, default=dict)
    code_hash = db.Column(db.String(64), nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    used_at = db.Column(db.DateTime, nullable=True)


class MobileAuthThrottle(db.Model):
    __tablename__ = "mobile_auth_throttles"
    key = db.Column(db.String(64), primary_key=True)
    window_at = db.Column(db.DateTime, nullable=False)
    last_at = db.Column(db.DateTime, nullable=False)
    count = db.Column(db.Integer, nullable=False, default=0)


class MobileAuthMail(db.Model):
    __tablename__ = "mobile_auth_mail"
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(
        db.String(64),
        db.ForeignKey("mobile_auth_challenges.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    email = db.Column(db.String(120), nullable=False)
    encrypted_code = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="pending", index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    locked_at = db.Column(db.DateTime, nullable=True)


class SocialIdentity(db.Model):
    __tablename__ = "social_identities"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = db.Column(db.String(20), nullable=False)
    subject = db.Column(db.String(256), nullable=False)
    encrypted_refresh = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    __table_args__ = (
        db.UniqueConstraint("provider", "subject", name="uq_social_provider_subject"),
    )
