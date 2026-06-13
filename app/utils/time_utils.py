"""Timezone helpers shared across XP idempotency write-paths.

Both the curriculum-lesson path (``complete_lesson`` in
``app/curriculum/service.py``) and the linear/card-lesson path
(``complete_srs_session`` → ``maybe_award_curriculum_xp``) dedupe XP by
``(user_id, local_date, lesson_id)``. If the two paths resolve the local
date differently, a user finishing a lesson near midnight can be awarded
XP twice — once under the UTC date and once under the user's tz date.

``get_user_local_date`` is the single source of truth: read
``User.timezone`` (falling back to ``config.settings.DEFAULT_TIMEZONE``
then UTC) and return ``datetime.now(tz).date()``.
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

from app.utils.request_cache import request_memoize


# Memoized by user_id only (NOT db_session) — audit E-011. This relies on the
# one-session-per-request invariant: a user's timezone is stable within a
# request, so the first resolved value is reused regardless of which session
# object later callers pass. Tests that drive multiple sessions/users inside a
# single request scope must not assume a fresh lookup per session.
@request_memoize(key_fn=lambda user_id, *_a, **_k: user_id)
def _get_user_timezone(user_id: int, db_session: Any = None):
    from zoneinfo import ZoneInfo

    from app.auth.models import User
    from app.utils.db import db
    from config.settings import DEFAULT_TIMEZONE

    db_obj = db_session if db_session is not None else db
    # db_obj may be a Flask-SQLAlchemy extension (has .session) or a raw
    # scoped_session passed directly from tests/callers.
    session_obj = db_obj.session if hasattr(db_obj, 'session') else db_obj
    user = session_obj.get(User, user_id)
    tz_name: Optional[str] = getattr(user, 'timezone', None) or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def get_user_local_date(
    user_id: int,
    db_session: Any = None,
) -> date_cls:
    """Return today's date in the user's timezone.

    Falls back to ``config.settings.DEFAULT_TIMEZONE`` when the user has
    no timezone set, and to UTC if that value fails to resolve (e.g. on
    a malformed override).
    """
    tz_obj = _get_user_timezone(user_id, db_session)
    return datetime.now(tz_obj).date()


def get_user_local_hour(
    user_id: int,
    db_session: Any = None,
) -> int:
    """Return the current hour (0-23) in the user's timezone."""
    tz_obj = _get_user_timezone(user_id, db_session)
    return datetime.now(tz_obj).hour


def get_user_local_day_bounds(
    user_id: int,
    db_session: Any = None,
) -> tuple[datetime, datetime]:
    """Return UTC-naive bounds for the user's current local day.

    The returned tuple is ``(start_utc_naive, end_utc_naive)`` so callers can
    compare against legacy ``DateTime`` columns that store UTC timestamps
    without tzinfo.
    """
    start = day_to_naive_utc(user_id, db_session, days_ahead=0)
    return (start, start + timedelta(days=1))


def day_to_naive_utc(
    user_id: int,
    db_session: Any = None,
    days_ahead: int = 0,
    now_utc: Optional[datetime] = None,
) -> datetime:
    """Return midnight of ``(today_local + days_ahead)`` as naive UTC.

    Single source of truth for SRS day-based scheduling and counters:
    cards are always written/compared at the start of the user's local
    day so that "today" semantics stay consistent across UTC boundaries.

    ``now_utc`` lets tests freeze the reference clock (aware or naive UTC).
    """
    tz_obj = _get_user_timezone(user_id, db_session)
    if now_utc is None:
        now_local = datetime.now(tz_obj)
    else:
        ref = now_utc if now_utc.tzinfo is not None else now_utc.replace(tzinfo=timezone.utc)
        now_local = ref.astimezone(tz_obj)
    target_local_date = (now_local + timedelta(days=days_ahead)).date()
    target_local_midnight = datetime.combine(target_local_date, time.min, tzinfo=tz_obj)
    return target_local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


def minutes_to_day_offset(
    user_id: int,
    db_session: Any = None,
    minutes: int = 0,
    now_utc: Optional[datetime] = None,
) -> int:
    """How many local days from now ``minutes`` ahead lands on.

    Used by SRS grading to translate intra-day learning steps (1/10/1440
    min) into a day offset for ``next_review``: a 10-min step at 10:00 is
    same-day (offset 0); the same step at 23:55 crosses to tomorrow
    (offset 1).
    """
    tz_obj = _get_user_timezone(user_id, db_session)
    if now_utc is None:
        now_local = datetime.now(tz_obj)
    else:
        ref = now_utc if now_utc.tzinfo is not None else now_utc.replace(tzinfo=timezone.utc)
        now_local = ref.astimezone(tz_obj)
    target_local = now_local + timedelta(minutes=minutes)
    return (target_local.date() - now_local.date()).days
