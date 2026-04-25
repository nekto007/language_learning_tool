"""Reading-session model + helpers for the reading-slot time gate.

The reading slot used to credit completion on any 5% offset delta — easily
farmed by scrolling. ``UserReadingSession`` captures actual time-on-page
so the slot's XP path can require both ``offset_delta >= 0.05`` AND
``time_spent >= MIN_READING_SECONDS``.

Frontend lifecycle:
    - ``POST /api/books/reading-session/start`` on chapter open / scroll-in
    - ``POST /api/books/reading-session/end``   on page-leave / scroll-out

A session's ``ended_at`` is nullable — an in-progress (open) session
contributes 0 seconds to the duration sum until it is closed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer

from app.utils.db import db


MIN_READING_SECONDS = 60


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserReadingSession(db.Model):
    __tablename__ = 'user_reading_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
    )
    chapter_id = Column(
        Integer,
        ForeignKey('chapter.id', ondelete='CASCADE'),
        nullable=False,
    )
    started_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    offset_delta = Column(Float, default=0.0, nullable=False)

    __table_args__ = (
        Index('idx_user_reading_session_user_chapter', 'user_id', 'chapter_id'),
        Index('idx_user_reading_session_started', 'started_at'),
    )

    def duration_seconds(self) -> int:
        if self.ended_at is None or self.started_at is None:
            return 0
        return max(0, int((self.ended_at - self.started_at).total_seconds()))

    def __repr__(self) -> str:
        return (
            f'<UserReadingSession id={self.id} user={self.user_id} '
            f'chapter={self.chapter_id} duration={self.duration_seconds()}s>'
        )


def start_session(user_id: int, chapter_id: int, db_session: Any = db) -> UserReadingSession:
    """Open a new reading session. Caller commits."""
    session = UserReadingSession(
        user_id=user_id,
        chapter_id=chapter_id,
        started_at=_utcnow(),
    )
    db_session.session.add(session)
    db_session.session.flush()
    return session


def end_session(
    session_id: int,
    offset_delta: float,
    db_session: Any = db,
) -> Optional[UserReadingSession]:
    """Close an open session. Returns the row, or ``None`` if not found.

    Idempotent: a re-call on an already-closed session keeps the original
    ``ended_at`` and only widens ``offset_delta`` if the new value is larger.
    """
    session = db_session.session.get(UserReadingSession, session_id)
    if session is None:
        return None
    if session.ended_at is None:
        session.ended_at = _utcnow()
    session.offset_delta = max(session.offset_delta or 0.0, float(offset_delta or 0.0))
    db_session.session.flush()
    return session


def _user_local_day_window_utc(user_id: int, db_session: Any) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) bracketing the user's local day."""
    from app.utils.time_utils import get_user_local_date
    from app.daily_plan.linear.xp import _get_user_timezone

    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        from backports.zoneinfo import ZoneInfo  # type: ignore

    today = get_user_local_date(user_id, db_session)
    tz_name = _get_user_timezone(user_id, db_session)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001
        tz = timezone.utc

    start_local = datetime(today.year, today.month, today.day, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def get_session_duration(
    user_id: int,
    chapter_id: int,
    db_session: Any = db,
) -> int:
    """Sum the duration (in seconds) of *closed* sessions for the user's
    local day, scoped to ``chapter_id``.

    Open sessions (``ended_at is None``) contribute 0 — closing the session
    is the signal that the user actually finished a reading window.
    """
    start_utc, end_utc = _user_local_day_window_utc(user_id, db_session)
    rows = (
        db_session.session.query(UserReadingSession)
        .filter(
            UserReadingSession.user_id == user_id,
            UserReadingSession.chapter_id == chapter_id,
            UserReadingSession.started_at >= start_utc,
            UserReadingSession.started_at < end_utc,
            UserReadingSession.ended_at.isnot(None),
        )
        .all()
    )
    return sum(r.duration_seconds() for r in rows)


def has_min_reading_time_today(
    user_id: int,
    book_id: int,
    db_session: Any = db,
    minimum_seconds: int = MIN_READING_SECONDS,
) -> bool:
    """Return True when total closed-session time for any chapter of
    ``book_id`` reached ``minimum_seconds`` within the user's local day.
    """
    from app.books.models import Chapter

    start_utc, end_utc = _user_local_day_window_utc(user_id, db_session)
    rows = (
        db_session.session.query(UserReadingSession)
        .join(Chapter, Chapter.id == UserReadingSession.chapter_id)
        .filter(
            UserReadingSession.user_id == user_id,
            Chapter.book_id == book_id,
            UserReadingSession.started_at >= start_utc,
            UserReadingSession.started_at < end_utc,
            UserReadingSession.ended_at.isnot(None),
        )
        .all()
    )
    total = sum(r.duration_seconds() for r in rows)
    return total >= minimum_seconds
