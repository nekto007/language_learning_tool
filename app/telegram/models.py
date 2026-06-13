"""Telegram bot models: user linking and temporary codes."""
import logging
import secrets
from datetime import date as date_cls
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import relationship

from app.utils.db import db

logger = logging.getLogger(__name__)


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


class TelegramNotificationLog(db.Model):
    """Idempotency marker: one scheduled notification per (user, kind, local day).

    The scheduler may briefly run in more than one process — across gunicorn
    workers, the dedicated scheduler container, or transiently during a deploy
    when an old and new container overlap. The advisory lock in
    ``init_scheduler`` keeps that to one in steady state, but this table is the
    hard guarantee: ``claim()`` does a race-safe insert against the UNIQUE
    constraint, so only the first caller for a given (user, kind, date) gets to
    send. ``sent_on`` is the user's LOCAL date (notification times are
    user-local), so the marker lines up with what the user actually sees.
    """

    __tablename__ = 'telegram_notification_log'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    kind = Column(String(20), nullable=False)  # tgn_morning, tgn_wotd, ...
    sent_on = Column(Date, nullable=False)      # user-local date
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'kind', 'sent_on', name='uq_tg_notif_user_kind_date'),
        Index('idx_tg_notif_user_date', 'user_id', 'sent_on'),
    )

    @classmethod
    def claim(cls, user_id: int, kind: str, local_date: 'date_cls') -> bool:
        """Atomically claim the right to send (user_id, kind, local_date).

        Returns True exactly once per key — the caller that gets True should
        send; everyone else gets False and must skip. Race-safe via the UNIQUE
        constraint + savepoint, so concurrent scheduler processes can't both
        send. Flush only — the caller commits.
        """
        try:
            with db.session.begin_nested():
                db.session.add(cls(user_id=user_id, kind=kind, sent_on=local_date))
                db.session.flush()
            return True
        except IntegrityError:
            # Someone already claimed this (user, kind, day).
            return False


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
