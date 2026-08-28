"""Timezone helpers shared across XP idempotency write-paths.

Both the curriculum-lesson path (``complete_lesson`` in
``app/curriculum/service.py``) and the linear/card-lesson path
(``complete_srs_session`` → ``maybe_award_curriculum_xp``) dedupe XP by
``(user_id, local_date, lesson_id)``. If the two paths resolve the local
date differently, a user finishing a lesson near midnight can be awarded
XP twice — once under the UTC date and once under the user's tz date.

``get_user_local_date`` is the single source of truth: read
``User.timezone`` (falling back to ``config.settings.DEFAULT_TIMEZONE``
then UTC) and return the learner's current *study-day* date.  A study day
starts at 02:00 local time, so a late-night session is not interrupted by a
calendar-midnight reset.
"""
from __future__ import annotations

from datetime import date as date_cls
from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

from app.utils.request_cache import request_memoize


# A learner who starts a session before midnight should not see their plan,
# reading target, SRS budget, or streak split while they are still studying.
# This is deliberately a single global cutoff (rather than a per-screen
# workaround) so all daily features agree about what "today" means.
LEARNING_DAY_START_HOUR = 2


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


def get_user_timezone_name(user_id: int, db_session: Any = None) -> str:
    """Return the user's IANA timezone NAME (string), DEFAULT_TIMEZONE fallback.

    Distinct from :func:`_get_user_timezone`, which returns a ZoneInfo OBJECT.
    Callers that pass ``tz=`` to plan/summary builders need the string form;
    this is the single canonical source for it (audit E-007).
    """
    from app.auth.models import User
    from app.utils.db import db
    from config.settings import DEFAULT_TIMEZONE

    db_obj = db_session if db_session is not None else db
    session_obj = db_obj.session if hasattr(db_obj, 'session') else db_obj
    user = session_obj.get(User, user_id)
    return getattr(user, 'timezone', None) or DEFAULT_TIMEZONE


def get_user_local_date(
    user_id: int,
    db_session: Any = None,
) -> date_cls:
    """Return the current study-day date in the user's timezone.

    Falls back to ``config.settings.DEFAULT_TIMEZONE`` when the user has
    no timezone set, and to UTC if that value fails to resolve.  The study
    day begins at :data:`LEARNING_DAY_START_HOUR` local time: e.g. at 01:30
    on 5 August the returned date is 4 August.
    """
    tz_obj = _get_user_timezone(user_id, db_session)
    return _study_day_date(datetime.now(tz_obj))


def _study_day_date(now_local: datetime) -> date_cls:
    """Map an aware user-local timestamp to its study-day date."""
    if now_local.hour < LEARNING_DAY_START_HOUR:
        return (now_local - timedelta(days=1)).date()
    return now_local.date()


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
    """Return UTC-naive bounds for the user's current study day.

    The returned tuple is ``(start_utc_naive, end_utc_naive)`` so callers can
    compare against legacy ``DateTime`` columns that store UTC timestamps
    without tzinfo.
    """
    start = day_to_naive_utc(user_id, db_session, days_ahead=0)
    end = day_to_naive_utc(user_id, db_session, days_ahead=1)
    return (start, end)


def day_to_naive_utc(
    user_id: int,
    db_session: Any = None,
    days_ahead: int = 0,
    now_utc: Optional[datetime] = None,
) -> datetime:
    """Return study-day start of ``(today_local + days_ahead)`` as naive UTC.

    Single source of truth for SRS day-based scheduling and counters:
    cards are always written/compared at the start of the user's local
    day so that "today" semantics stay consistent across UTC boundaries.
    A study day begins at 02:00 in the user's timezone.

    ``now_utc`` lets tests freeze the reference clock (aware or naive UTC).
    """
    tz_obj = _get_user_timezone(user_id, db_session)
    if now_utc is None:
        now_local = datetime.now(tz_obj)
    else:
        ref = now_utc if now_utc.tzinfo is not None else now_utc.replace(tzinfo=timezone.utc)
        now_local = ref.astimezone(tz_obj)
    target_local_date = _study_day_date(now_local) + timedelta(days=days_ahead)
    target_local_start = datetime.combine(
        target_local_date,
        time(hour=LEARNING_DAY_START_HOUR),
        tzinfo=tz_obj,
    )
    return target_local_start.astimezone(timezone.utc).replace(tzinfo=None)


def _local_now_for_tz_name(
    tz_name: str,
    now_utc: Optional[datetime] = None,
) -> tuple[Any, datetime]:
    """Resolve a timezone NAME to ``(tz, local_now)`` — pytz, DEFAULT_TIMEZONE fallback.

    Kept separate from :func:`_get_user_timezone` (ZoneInfo, ``user_id``-keyed,
    UTC fallback) on purpose: this is the historical ``_user_day_boundaries``
    resolution policy, preserved verbatim.  The two fallbacks disagreeing on an
    unknown zone is audit finding DP-082, deliberately out of scope here.
    """
    import pytz

    from config.settings import DEFAULT_TIMEZONE

    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        tz = pytz.timezone(DEFAULT_TIMEZONE)

    if now_utc is None:
        return tz, datetime.now(tz)
    ref = now_utc if now_utc.tzinfo is not None else now_utc.replace(tzinfo=timezone.utc)
    return tz, ref.astimezone(tz)


def study_day_start_utc(tz_name: str, local_date: date_cls) -> datetime:
    """Aware-UTC start of the study day whose date is ``local_date``.

    The one place that turns "study day D in zone Z" into an instant: the
    anchor is :data:`LEARNING_DAY_START_HOUR` local, never calendar midnight.
    :func:`study_day_bounds_utc` (relative to now) and the snapshot roll-over
    window (an explicit past date) both go through here, so a window built
    from a stored date and a window built from the clock cannot drift apart.

    Timezone resolution keeps the historical ``_user_day_boundaries`` policy
    verbatim — see :func:`_local_now_for_tz_name`.
    """
    import pytz

    from config.settings import DEFAULT_TIMEZONE

    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        tz = pytz.timezone(DEFAULT_TIMEZONE)
    naive = datetime.combine(local_date, time(hour=LEARNING_DAY_START_HOUR))
    return tz.normalize(tz.localize(naive)).astimezone(pytz.utc)


def study_day_bounds_utc(
    tz_name: str,
    offset_days: int = 0,
    now_utc: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """Return aware-UTC ``(start, end)`` of a study day for a timezone NAME.

    The single canonical window helper for "did this user study on day X?".
    Same day, different return shape than :func:`get_user_local_day_bounds`
    (which is keyed on ``user_id`` and returns naive UTC): both anchor at
    :data:`LEARNING_DAY_START_HOUR` local, so streak math, telegram windows,
    SRS counters, and XP dedup keys all agree about what "today" means.

    ``offset_days=-1`` is the previous study day, etc.  Windows are
    contiguous: ``bounds(-1)[1] == bounds(0)[0]``.

    Timezone resolution keeps the historical ``_user_day_boundaries`` policy
    verbatim — see :func:`_local_now_for_tz_name`.

    ``now_utc`` lets callers/tests freeze the reference clock.
    """
    _tz, local_now = _local_now_for_tz_name(tz_name, now_utc)
    base_day = _study_day_date(local_now)

    def _start(shift: int) -> datetime:
        return study_day_start_utc(tz_name, base_day + timedelta(days=shift))

    return _start(offset_days), _start(offset_days + 1)


def study_day_date_for_tz(
    tz_name: str,
    now_utc: Optional[datetime] = None,
) -> date_cls:
    """Study-day date for a timezone NAME (companion to :func:`study_day_bounds_utc`).

    ``get_user_local_date`` answers the same question keyed on ``user_id``;
    this form is for callers that already hold the zone name (streak repair
    walkers, telegram queries) and must not derive dates on a second basis.
    """
    _tz, local_now = _local_now_for_tz_name(tz_name, now_utc)
    return _study_day_date(local_now)


def naive_utc_to_user_local(
    user_id: int,
    value: Optional[datetime],
    db_session: Any = None,
) -> Optional[datetime]:
    """Inverse of :func:`day_to_naive_utc` for display.

    SRS datetime columns hold the user's local day start projected to naive
    UTC. Rendering them straight (``value.strftime(...)``) prints the UTC
    instant, which for any eastern timezone is the *previous* calendar day —
    a rest ending on the 10th showed up as "до 09.09".
    """
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(_get_user_timezone(user_id, db_session))


def naive_utc_to_user_local_date(
    user_id: int,
    value: Optional[datetime],
    db_session: Any = None,
) -> Optional[date_cls]:
    """Local calendar date of a naive-UTC SRS timestamp."""
    local = naive_utc_to_user_local(user_id, value, db_session)
    return local.date() if local is not None else None


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
    return (_study_day_date(target_local) - _study_day_date(now_local)).days
