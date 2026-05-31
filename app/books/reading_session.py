"""Reading-session model + helpers for the reading-slot time gate.

The reading slot used to credit completion on any 5% offset delta — easily
farmed by scrolling. ``UserReadingSession`` captures actual time-on-page
so the slot's XP path can require both ``offset_delta >= 0.05`` AND
``time_spent >= MIN_READING_SECONDS``.

Frontend lifecycle:
    - ``POST /api/books/reading-session/start`` on chapter open / scroll-in
    - ``POST /api/books/reading-session/end``   on page-leave / scroll-out

A session's ``ended_at`` is nullable. Open sessions are still credited
*conservatively* (capped at ``OPEN_SESSION_GRACE_SECONDS``) by the daily
helpers below so that a sendBeacon-delivered close racing with a
dashboard rebuild does not strip already-read minutes from the reading
slot. The grace cap matches one client heartbeat window plus network
slack, so a stale open session can never over-credit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, and_, or_
from sqlalchemy.exc import IntegrityError

from app.utils.db import db


# Legacy per-session thresholds (still used by /save_reading_position and the
# linear XP path for the older one-session-must-qualify rule).
MIN_READING_SECONDS = 300

# Daily-target thresholds for the unified plan reading slot. These gate the
# "Дневная норма по чтению выполнена" banner and the slot's completion event.
# Aggregated across all of today's sessions on the same chapter — so
# pause/resume cycles (which split a long read into many short sessions) are
# summed honestly.
DAILY_READING_TARGET_SECONDS = 300
# Per-chapter offset-advance gate for the daily reading target. Set to 0 so
# the slot completes on time alone: idle-pause (60s no activity → no time
# accrued) + 60s heartbeat + ``OPEN_SESSION_GRACE_SECONDS`` cap already
# guarantee 5min means active engagement, and a chapter that fits in one
# viewport (short chapter / large reader) needs no scrolling to be read.
DAILY_CHAPTER_ADVANCE_MIN = 0.0
CHAPTER_COMPLETION_THRESHOLD = 0.99

# Max seconds we credit to an in-progress (still-open) session. Matches the
# reader's heartbeat interval (60s, see ``HEARTBEAT_INTERVAL_MS`` in
# ``reader_simple.html``) plus a 30s slack for network latency. A stale open
# session — e.g. a tab the user walked away from — cannot exceed this cap
# regardless of wall-clock age, so the grace window is bounded.
OPEN_SESSION_GRACE_SECONDS = 90


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _session_credit_seconds(
    session: 'UserReadingSession', now: Optional[datetime] = None
) -> int:
    """Seconds to credit for one session, treating open sessions as actively
    read for at most ``OPEN_SESSION_GRACE_SECONDS``.

    Closes the race where a user navigates from the reader to the
    dashboard before the sendBeacon close has committed: the open row
    is still visible and credited up to one heartbeat window, matching
    what would have committed had the close request arrived.
    """
    if session.ended_at is not None:
        return session.duration_seconds()
    if session.started_at is None:
        return 0
    now = now or _utcnow()
    elapsed = int((now - session.started_at).total_seconds())
    if elapsed <= 0:
        return 0
    return min(elapsed, OPEN_SESSION_GRACE_SECONDS)


def _sessions_in_local_day_filter(start_utc: datetime, end_utc: datetime):
    """SQLAlchemy predicate matching closed sessions by ``ended_at`` AND
    open sessions by ``started_at`` within the user's local-day window.

    Open sessions are anchored on ``started_at`` because they have no
    ``ended_at`` yet — we credit them today if they were begun today.
    """
    return or_(
        and_(
            UserReadingSession.ended_at.isnot(None),
            UserReadingSession.ended_at >= start_utc,
            UserReadingSession.ended_at < end_utc,
        ),
        and_(
            UserReadingSession.ended_at.is_(None),
            UserReadingSession.started_at >= start_utc,
            UserReadingSession.started_at < end_utc,
        ),
    )


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
    start_offset_pct = Column(Float, default=0.0, nullable=False)
    offset_delta = Column(Float, default=0.0, nullable=False)

    __table_args__ = (
        Index('idx_user_reading_session_user_chapter', 'user_id', 'chapter_id'),
        Index('idx_user_reading_session_started', 'started_at'),
        # Partial unique index: at most one open session per (user, chapter).
        # Two concurrent /reading-session/start requests would otherwise both
        # see zero open rows and both insert; the loser of the race would
        # persist as a second open session whose later /end could combine its
        # 60s duration with the active tab's progress for a qualifying delta.
        Index(
            'uq_user_reading_session_open',
            'user_id', 'chapter_id',
            unique=True,
            sqlite_where=ended_at.is_(None),
            postgresql_where=ended_at.is_(None),
        ),
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


def _current_chapter_offset(user_id: int, chapter_id: int, db_session: Any) -> float:
    from app.books.models import UserChapterProgress

    progress = (
        db_session.session.query(UserChapterProgress)
        .filter_by(user_id=user_id, chapter_id=chapter_id)
        .first()
    )
    return float(progress.offset_pct) if progress and progress.offset_pct is not None else 0.0


def start_session(user_id: int, chapter_id: int, db_session: Any = db) -> UserReadingSession:
    """Open a new reading session. Caller commits.

    Snapshots the user's current ``UserChapterProgress.offset_pct`` so that
    ``end_session`` can compute the per-visit delta server-side without
    trusting any client payload.

    Auto-closes any still-open session for the same ``(user, chapter)`` pair
    first. Without this, two concurrent tabs on the same chapter would both
    snapshot the same start offset; whichever tab actually scrolled would
    grow the persisted offset, and the *idle* tab's later close would still
    compute a qualifying ``offset_delta`` from the other tab's progress —
    minting reading XP for time that was not paired with progress.

    Race-safe: a partial unique index guarantees at most one open session
    per ``(user, chapter)``. If a concurrent ``start_session`` wins the
    insert race, this call retries the close-and-insert sequence under a
    savepoint so the loser also ends up with a single fresh open row
    rather than colliding on the index.
    """
    for _attempt in range(3):
        now = _utcnow()
        open_sessions = (
            db_session.session.query(UserReadingSession)
            .filter(
                UserReadingSession.user_id == user_id,
                UserReadingSession.chapter_id == chapter_id,
                UserReadingSession.ended_at.is_(None),
            )
            .all()
        )
        if open_sessions:
            current = _current_chapter_offset(user_id, chapter_id, db_session)
            for prior in open_sessions:
                # Cap auto-close duration to one heartbeat window. Without this,
                # a tab abandoned hours ago (whose /reading-session/end never
                # fired) would, on the next /start, be closed with the full
                # wall-clock gap as ``ended_at - started_at`` and credited as
                # active reading — enough to trip the daily target and award
                # the slot/XP immediately. Matches the in-progress grace cap
                # in ``_session_credit_seconds`` so closed and still-open
                # stale sessions are treated symmetrically.
                if prior.started_at is not None:
                    elapsed = int((now - prior.started_at).total_seconds())
                    capped = max(0, min(elapsed, OPEN_SESSION_GRACE_SECONDS))
                    prior.ended_at = prior.started_at + timedelta(seconds=capped)
                else:
                    prior.ended_at = now
                prior.offset_delta = max(
                    0.0, current - float(prior.start_offset_pct or 0.0)
                )
            db_session.session.flush()

        session = UserReadingSession(
            user_id=user_id,
            chapter_id=chapter_id,
            started_at=now,
            start_offset_pct=_current_chapter_offset(user_id, chapter_id, db_session),
        )
        try:
            with db_session.session.begin_nested():
                db_session.session.add(session)
                db_session.session.flush()
        except IntegrityError:
            # A concurrent transaction inserted an open row between our
            # SELECT and INSERT. Loop to close it and retry.
            continue
        return session
    raise RuntimeError(
        f'start_session: failed to create open row for user={user_id} '
        f'chapter={chapter_id} after 3 attempts'
    )


def end_session(
    session_id: int,
    db_session: Any = db,
    current_offset_pct: Optional[float] = None,
) -> Optional[UserReadingSession]:
    """Close an open session. Returns the row, or ``None`` if not found.

    ``offset_delta`` is computed server-side as
    ``max(0, current_offset_pct - start_offset_pct)`` from the user's
    ``UserChapterProgress`` for the session's chapter, so a forged
    request cannot mint reading XP without the user actually
    progressing through the chapter in this visit.

    ``current_offset_pct`` is an optional client hint used only when the
    session is being closed for the first time. The reader debounces
    progress saves by 3s, so the persisted ``UserChapterProgress`` may
    lag the latest scroll on page-leave. When the hint exceeds the
    persisted offset, this function ALSO writes the hint to
    ``UserChapterProgress`` (via ``max(stored, hint)``) so that using
    the hint cannot mint reading XP without leaving the same persisted
    progress trail that a separate ``PATCH /api/progress`` call would.

    Idempotent and lock-on-close: a re-call on an already-closed session
    is a no-op for ``ended_at`` and ``offset_delta``. This prevents a
    replay attack where a user closes a 60s/no-progress session, makes a
    small scroll nudge in a later session, then re-sends the old
    ``session_id`` to retroactively combine the old visit's duration
    with the later visit's progress.
    """
    from app.books.models import UserChapterProgress

    session = db_session.session.get(UserReadingSession, session_id)
    if session is None:
        return None
    if session.ended_at is not None:
        return session
    session.ended_at = _utcnow()
    current = _current_chapter_offset(session.user_id, session.chapter_id, db_session)
    if current_offset_pct is not None:
        try:
            hint = float(current_offset_pct)
        except (TypeError, ValueError):
            hint = 0.0
        hint = max(0.0, min(1.0, hint))
        if hint > current:
            # Persist the hint to UserChapterProgress so the XP-qualifying
            # offset_delta is matched by a real progress signal — no
            # ephemeral, side-effect-free XP minting via the hint alone.
            progress = (
                db_session.session.query(UserChapterProgress)
                .filter_by(user_id=session.user_id, chapter_id=session.chapter_id)
                .first()
            )
            if progress is None:
                progress = UserChapterProgress(
                    user_id=session.user_id,
                    chapter_id=session.chapter_id,
                    offset_pct=hint,
                )
                db_session.session.add(progress)
            else:
                progress.offset_pct = hint
                # Match the /progress save path: consumers (reading slot,
                # streak service) treat updated_at as the "last read"
                # signal, so the unload-hint write must refresh it too.
                progress.updated_at = _utcnow()
            current = hint
    delta = max(0.0, current - float(session.start_offset_pct or 0.0))
    session.offset_delta = delta
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
    """Sum the seconds spent in ``chapter_id`` today.

    Closed sessions are credited for their full ``duration_seconds()``;
    still-open sessions are credited up to ``OPEN_SESSION_GRACE_SECONDS``
    so a sendBeacon close that hasn't committed yet doesn't make
    already-read time disappear from the slot. Closed sessions are
    bucketed by ``ended_at`` so a midnight-crossing session is credited
    to the day the user actually finished reading.
    """
    start_utc, end_utc = _user_local_day_window_utc(user_id, db_session)
    rows = (
        db_session.session.query(UserReadingSession)
        .filter(
            UserReadingSession.user_id == user_id,
            UserReadingSession.chapter_id == chapter_id,
            _sessions_in_local_day_filter(start_utc, end_utc),
        )
        .all()
    )
    now = _utcnow()
    return sum(_session_credit_seconds(r, now) for r in rows)


def get_book_reading_seconds_today(
    user_id: int,
    book_id: int,
    db_session: Any = db,
) -> int:
    """Total seconds spent reading any chapter of ``book_id`` today.

    Closed sessions count for ``duration_seconds()``; still-open ones
    contribute up to ``OPEN_SESSION_GRACE_SECONDS`` (one heartbeat
    window) so a sendBeacon close racing with the dashboard rebuild
    can't strip already-read time from the slot. Used by the unified
    reading slot to surface "Прочитано N сек / 300 сек" progress.
    """
    from app.books.models import Chapter

    start_utc, end_utc = _user_local_day_window_utc(user_id, db_session)
    rows = (
        db_session.session.query(UserReadingSession)
        .join(Chapter, Chapter.id == UserReadingSession.chapter_id)
        .filter(
            UserReadingSession.user_id == user_id,
            Chapter.book_id == book_id,
            _sessions_in_local_day_filter(start_utc, end_utc),
        )
        .all()
    )
    now = _utcnow()
    return sum(_session_credit_seconds(r, now) for r in rows)


def has_min_reading_time_today(
    user_id: int,
    book_id: int,
    db_session: Any = db,
    minimum_seconds: int = MIN_READING_SECONDS,
) -> bool:
    """Return True when total reading time for any chapter of ``book_id``
    reached ``minimum_seconds`` within the user's local day.

    Includes still-open sessions credited up to one heartbeat window so
    a sendBeacon-close racing with the dashboard rebuild doesn't drop
    the slot back to incomplete.
    """
    from app.books.models import Chapter

    start_utc, end_utc = _user_local_day_window_utc(user_id, db_session)
    rows = (
        db_session.session.query(UserReadingSession)
        .join(Chapter, Chapter.id == UserReadingSession.chapter_id)
        .filter(
            UserReadingSession.user_id == user_id,
            Chapter.book_id == book_id,
            _sessions_in_local_day_filter(start_utc, end_utc),
        )
        .all()
    )
    now = _utcnow()
    total = sum(_session_credit_seconds(r, now) for r in rows)
    return total >= minimum_seconds


def has_qualifying_reading_session_today(
    user_id: int,
    book_id: int,
    db_session: Any = db,
    minimum_seconds: int = MIN_READING_SECONDS,
    minimum_offset_delta: float = 0.05,
) -> bool:
    """Return True iff at least one closed session today on a chapter of
    ``book_id`` met BOTH duration and per-visit offset-delta thresholds.

    Per-session enforcement (vs. summing across sessions) closes the
    bypass where a user spends 60s in one visit, reopens later, nudges
    the scroll by a tiny amount, and still trips the slot — the second
    visit's session would not itself qualify.
    """
    from app.books.models import Chapter

    start_utc, end_utc = _user_local_day_window_utc(user_id, db_session)
    rows = (
        db_session.session.query(UserReadingSession)
        .join(Chapter, Chapter.id == UserReadingSession.chapter_id)
        .filter(
            UserReadingSession.user_id == user_id,
            Chapter.book_id == book_id,
            UserReadingSession.ended_at.isnot(None),
            UserReadingSession.ended_at >= start_utc,
            UserReadingSession.ended_at < end_utc,
            UserReadingSession.offset_delta >= minimum_offset_delta,
        )
        .all()
    )
    return any(r.duration_seconds() >= minimum_seconds for r in rows)


def compute_chapter_daily_target_state(
    user_id: int,
    chapter_id: int,
    db_session: Any = db,
) -> dict:
    """Aggregate today's reading state for one chapter.

    Returns a dict describing whether the user has met the "daily reading
    target" inside this chapter today AND whether the chapter has just been
    completed during today's sessions:

    - ``active_seconds`` — sum of session durations today on this chapter.
      Closed sessions contribute their full ``duration_seconds()``; an
      in-progress session contributes up to ``OPEN_SESSION_GRACE_SECONDS``
      so the slot doesn't temporarily un-complete while the close request
      is in flight.
    - ``earliest_start_offset`` — lowest ``start_offset_pct`` of today's sessions
    - ``current_offset`` — current persisted ``UserChapterProgress.offset_pct``
    - ``offset_advance`` — ``max(0, current - earliest_start)``
    - ``chapter_completed_today`` — earliest_start < threshold AND current >= threshold
    - ``daily_target_met`` — ``active_seconds >= DAILY_READING_TARGET_SECONDS``
      (and ``offset_advance >= DAILY_CHAPTER_ADVANCE_MIN``, which defaults
      to 0 so time alone closes the slot; raise the constant to re-enable
      a scroll-engagement gate)

    Aggregation across sessions (rather than per-session) is intentional:
    pause/resume cycles split a continuous read into many short sessions
    (auto-pause on tab hidden / idle / manual pause). Summing honours the
    real active reading time without penalising honest pauses.
    """
    start_utc, end_utc = _user_local_day_window_utc(user_id, db_session)
    sessions = (
        db_session.session.query(UserReadingSession)
        .filter(
            UserReadingSession.user_id == user_id,
            UserReadingSession.chapter_id == chapter_id,
            _sessions_in_local_day_filter(start_utc, end_utc),
        )
        .all()
    )
    now = _utcnow()
    active_seconds = sum(_session_credit_seconds(s, now) for s in sessions)
    earliest_start = min(
        (float(s.start_offset_pct or 0.0) for s in sessions),
        default=0.0,
    )
    current_offset = _current_chapter_offset(user_id, chapter_id, db_session)
    offset_advance = max(0.0, current_offset - earliest_start)
    chapter_completed_today = (
        bool(sessions)
        and earliest_start < CHAPTER_COMPLETION_THRESHOLD
        and current_offset >= CHAPTER_COMPLETION_THRESHOLD
    )
    daily_target_met = (
        active_seconds >= DAILY_READING_TARGET_SECONDS
        and offset_advance >= DAILY_CHAPTER_ADVANCE_MIN
    )
    return {
        'active_seconds': active_seconds,
        'earliest_start_offset': earliest_start,
        'current_offset': current_offset,
        'offset_advance': offset_advance,
        'chapter_completed_today': chapter_completed_today,
        'daily_target_met': daily_target_met,
    }


def is_daily_reading_target_met_today(
    user_id: int,
    book_id: int,
    db_session: Any = db,
) -> bool:
    """Return True iff any chapter of ``book_id`` reached the daily target
    today (aggregated time + offset advance). Used by the unified daily
    plan reading slot to decide completion.

    Open sessions count toward both the chapter shortlist and the
    per-chapter aggregate via ``compute_chapter_daily_target_state``, so
    a navigation from the reader straight to the dashboard no longer
    needs the sendBeacon close to land before the slot can flip.
    """
    from app.books.models import Chapter

    start_utc, end_utc = _user_local_day_window_utc(user_id, db_session)
    chapter_rows = (
        db_session.session.query(UserReadingSession.chapter_id)
        .join(Chapter, Chapter.id == UserReadingSession.chapter_id)
        .filter(
            UserReadingSession.user_id == user_id,
            Chapter.book_id == book_id,
            _sessions_in_local_day_filter(start_utc, end_utc),
        )
        .distinct()
        .all()
    )
    for (chapter_id,) in chapter_rows:
        state = compute_chapter_daily_target_state(user_id, chapter_id, db_session)
        if state['daily_target_met']:
            return True
    return False
