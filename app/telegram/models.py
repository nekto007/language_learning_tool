"""Telegram bot models: user linking and temporary codes."""
import secrets
from datetime import datetime, timezone, timedelta

from sqlalchemy import Column, Integer, SmallInteger, BigInteger, String, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.utils.db import db


class TelegramUser(db.Model):
    """Links a Telegram account to a site user."""

    __tablename__ = 'telegram_users_v2'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True)
    telegram_id = Column(BigInteger, nullable=False, unique=True)
    username = Column(String(64))
    timezone = Column(String(50), default='Europe/Moscow', nullable=False)

    # Notification preferences
    morning_reminder = Column(Boolean, default=True, nullable=False)
    evening_summary = Column(Boolean, default=True, nullable=False)
    nudge_enabled = Column(Boolean, default=True, nullable=False)
    streak_alert = Column(Boolean, default=True, nullable=False)

    # Custom notification times (hour in user's timezone)
    morning_hour = Column(SmallInteger, default=9, nullable=False)
    nudge_hour = Column(SmallInteger, default=14, nullable=False)
    evening_hour = Column(SmallInteger, default=21, nullable=False)
    streak_hour = Column(SmallInteger, default=22, nullable=False)

    # Reflection after evening summary
    last_reflection = Column(String(10))       # 'hard', 'ok', 'easy'
    last_reflection_at = Column(DateTime)

    linked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    user = relationship('User', backref='telegram_account', uselist=False)

    __table_args__ = (
        Index('idx_telegram_users_v2_telegram_id', 'telegram_id'),
        Index('idx_telegram_users_v2_user_id', 'user_id'),
    )

    def __repr__(self):
        return f"<TelegramUser {self.telegram_id} -> user={self.user_id}>"

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'telegram_id': self.telegram_id,
            'username': self.username,
            'timezone': self.timezone,
            'morning_reminder': self.morning_reminder,
            'evening_summary': self.evening_summary,
            'nudge_enabled': self.nudge_enabled,
            'streak_alert': self.streak_alert,
            'linked_at': self.linked_at.isoformat() if self.linked_at else None,
            'is_active': self.is_active,
        }


class TelegramLinkCode(db.Model):
    """Temporary 6-digit code for linking Telegram to site account."""

    __tablename__ = 'telegram_link_codes_v2'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    code = Column(String(6), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship('User')

    def __repr__(self):
        return f"<TelegramLinkCode user={self.user_id} code={self.code}>"

    CODE_TTL_MINUTES = 15

    @classmethod
    def generate(cls, user_id: int) -> 'TelegramLinkCode':
        """Generate a new 6-digit link code for the user.

        Removes any existing codes for this user first.
        """
        # Remove old codes for this user
        cls.query.filter_by(user_id=user_id).delete()

        # Remove all expired codes
        cls.query.filter(cls.expires_at < datetime.now(timezone.utc)).delete()

        code = str(secrets.randbelow(900000) + 100000)  # 100000–999999
        link_code = cls(
            user_id=user_id,
            code=code,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=cls.CODE_TTL_MINUTES),
        )
        db.session.add(link_code)
        db.session.commit()
        return link_code

    @classmethod
    def verify(cls, code: str) -> 'TelegramLinkCode | None':
        """Find a valid (non-expired) link code."""
        return cls.query.filter(
            cls.code == code,
            cls.expires_at > datetime.now(timezone.utc),
        ).first()

    def consume(self) -> None:
        """Delete the code after successful linking."""
        db.session.delete(self)
        db.session.commit()


class PendingTelegramLink(db.Model):
    """Tracks two-step /link flow: user sent /link and is expected to send a code.

    Replaces the in-memory ``_pending_link`` dict so the state survives
    app restarts.
    """

    __tablename__ = 'pending_telegram_links'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, nullable=False, unique=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    PENDING_TTL_SECONDS = 300  # 5 minutes

    def __repr__(self) -> str:
        return f"<PendingTelegramLink telegram_id={self.telegram_id}>"

    @classmethod
    def create(cls, telegram_id: int) -> 'PendingTelegramLink':
        """Mark a telegram user as awaiting a link code.

        Upserts: if a pending record already exists, refreshes its timestamp.
        Also cleans up expired entries.
        """
        cls.cleanup_expired()

        existing = cls.query.filter_by(telegram_id=telegram_id).first()
        if existing:
            existing.created_at = datetime.now(timezone.utc)
            db.session.commit()
            return existing

        pending = cls(telegram_id=telegram_id)
        db.session.add(pending)
        db.session.commit()
        return pending

    @classmethod
    def is_pending(cls, telegram_id: int) -> bool:
        """Check if the user has a non-expired pending link."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=cls.PENDING_TTL_SECONDS)
        return cls.query.filter(
            cls.telegram_id == telegram_id,
            cls.created_at > cutoff,
        ).first() is not None

    @classmethod
    def remove(cls, telegram_id: int) -> None:
        """Remove pending state for a telegram user."""
        cls.query.filter_by(telegram_id=telegram_id).delete()
        db.session.commit()

    @classmethod
    def cleanup_expired(cls) -> None:
        """Delete all expired pending entries."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=cls.PENDING_TTL_SECONDS)
        cls.query.filter(cls.created_at <= cutoff).delete()
        db.session.commit()
