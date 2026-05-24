"""Linear daily plan metrics for the admin dashboard.

Post-rollout visibility into how the linear spine is performing across the
user base. Four aggregate ratios over the cohort of users with
``use_linear_plan = TRUE``:

- ``day_secured_rate`` — fraction of active cohort users whose
  ``DailyPlanLog.secured_at`` is populated today.
- ``average_slots_completed`` — mean number of baseline-slot proxies
  completed today across active cohort users, using DB activity as the
  proxy (curriculum lesson completion, study session, reading progress).
- ``error_review_trigger_rate`` — fraction of cohort users where the
  error-review trigger fires (≥5 unresolved quiz errors, cooldown elapsed).
- ``book_select_rate`` — fraction of cohort users with a
  ``UserReadingPreference`` row.
- ``reading_gate_completion_rate`` — fraction of cohort users who earned
  ``linear_book_reading`` XP today (i.e. cleared the ≥5% delta + ≥60s
  reading-time gate at least once).
- ``error_review_completion_rate`` — among cohort users with enough
  unresolved errors to qualify for the slot today (≥5 unresolved), the
  fraction who resolved at least one ``QuizErrorLog`` row today.
  Cooldown is intentionally ignored in the denominator so that users
  who *did* resolve work today are counted in both numerator and
  denominator. 0 when nobody qualifies.

- ``focus_distribution`` — count of cohort users in each
  ``onboarding_focus`` bucket (``grammar``/``vocabulary``/``reading``/
  ``all``/``none``).
- ``focus_average_slots`` — average ``slot_count`` per focus bucket
  (0.0 when the bucket is empty).

All metrics return floats in [0, 100] or absolute averages. When the
cohort is empty the helpers short-circuit to 0 — callers can rely on a
non-None payload regardless of rollout state.

Performance note: all helpers use a SQLAlchemy subquery for the cohort
definition (``SELECT id FROM users WHERE use_linear_plan = TRUE``) rather
than materialising user IDs into Python. This avoids O(cohort_size)
chunked IN() round-trips and keeps the query count constant regardless of
cohort size.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import case, func

from app.auth.models import User
from app.books.models import UserChapterProgress
from app.curriculum.models import LessonProgress
from app.daily_plan.linear.errors import (
    REVIEW_TRIGGER_MIN_UNRESOLVED,
    get_review_cooldown,
)
from app.daily_plan.linear.models import QuizErrorLog, UserReadingPreference
from app.daily_plan.models import DailyPlanLog
from app.study.models import StudySession
from app.utils.db import db
from app.utils.db_utils import chunk_ids


def _cohort_subquery(session: Any):
    """Subquery: SELECT id FROM users WHERE use_linear_plan = TRUE."""
    return session.query(User.id).filter(User.use_linear_plan.is_(True)).subquery()


def _cohort_size(session: Any) -> int:
    return (
        session.query(func.count(User.id))
        .filter(User.use_linear_plan.is_(True))
        .scalar()
        or 0
    )


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _day_secured_rate(cohort_subq: Any, total: int, today: date, session: Any) -> float:
    if not total:
        return 0.0
    secured = (
        session.query(func.count(DailyPlanLog.id))
        .filter(
            DailyPlanLog.user_id.in_(cohort_subq),
            DailyPlanLog.plan_date == today,
            DailyPlanLog.secured_at.isnot(None),
        )
        .scalar()
        or 0
    )
    return round(secured / total * 100, 1)


FOCUS_BUCKETS = ('grammar', 'vocabulary', 'reading', 'all', 'none')


def _classify_focus(raw: Optional[str]) -> str:
    """Bucket ``User.onboarding_focus`` into one of FOCUS_BUCKETS."""
    if not raw:
        return 'none'
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    if not parts:
        return 'none'
    primary = parts[0]
    if primary in FOCUS_BUCKETS and primary != 'none':
        return primary
    return 'none'


def _active_user_sets(
    cohort_subq: Any, today: date, session: Any
) -> tuple[set[int], set[int], set[int], set[int]]:
    """Return four sets of cohort user IDs active in each slot type today.

    Uses a single subquery IN() per activity source instead of chunked
    IN() clauses, giving O(1) query count regardless of cohort size.
    """
    curriculum: set[int] = {
        row[0]
        for row in session.query(LessonProgress.user_id)
        .filter(
            LessonProgress.user_id.in_(cohort_subq),
            LessonProgress.status == 'completed',
            func.date(LessonProgress.completed_at) == today,
        )
        .distinct()
        .all()
    }
    srs: set[int] = {
        row[0]
        for row in session.query(StudySession.user_id)
        .filter(
            StudySession.user_id.in_(cohort_subq),
            func.date(StudySession.start_time) == today,
        )
        .distinct()
        .all()
    }
    reading: set[int] = {
        row[0]
        for row in session.query(UserChapterProgress.user_id)
        .filter(
            UserChapterProgress.user_id.in_(cohort_subq),
            UserChapterProgress.updated_at.isnot(None),
            func.date(UserChapterProgress.updated_at) == today,
        )
        .distinct()
        .all()
    }
    error_rev: set[int] = {
        row[0]
        for row in session.query(QuizErrorLog.user_id)
        .filter(
            QuizErrorLog.user_id.in_(cohort_subq),
            QuizErrorLog.resolved_at.isnot(None),
            func.date(QuizErrorLog.resolved_at) == today,
        )
        .distinct()
        .all()
    }
    return curriculum, srs, reading, error_rev


def _average_slots_completed(
    total: int,
    active_sets: tuple[set[int], set[int], set[int], set[int]],
) -> float:
    """Compute average slots completed from pre-fetched active-user sets."""
    if not total:
        return 0.0
    curriculum, srs, reading, error_rev = active_sets
    total_slots = len(curriculum) + len(srs) + len(reading) + len(error_rev)
    return round(total_slots / total, 2)


def _focus_distribution_and_avg_slots(
    cohort_subq: Any,
    today: date,
    session: Any,
    active_sets: Optional[tuple[set[int], set[int], set[int], set[int]]] = None,
) -> tuple[dict[str, int], dict[str, float]]:
    """Return (counts_per_focus, avg_slots_per_focus) over the cohort.

    Fetches (user_id, onboarding_focus) for the whole cohort in a single
    query, then classifies each user into a focus bucket. Active-user sets
    are reused from ``active_sets`` when provided to avoid duplicate queries.
    """
    counts: dict[str, int] = {bucket: 0 for bucket in FOCUS_BUCKETS}
    sums: dict[str, int] = {bucket: 0 for bucket in FOCUS_BUCKETS}
    averages: dict[str, float] = {bucket: 0.0 for bucket in FOCUS_BUCKETS}

    cohort_rows = (
        session.query(User.id, User.onboarding_focus)
        .filter(User.use_linear_plan.is_(True))
        .all()
    )
    if not cohort_rows:
        return counts, averages

    if active_sets is None:
        active_sets = _active_user_sets(cohort_subq, today, session)

    curriculum_users, srs_users, reading_users, error_users = active_sets

    for uid, raw_focus in cohort_rows:
        bucket = _classify_focus(raw_focus)
        counts[bucket] += 1
        slot_count = (
            (1 if uid in curriculum_users else 0)
            + (1 if uid in srs_users else 0)
            + (1 if uid in reading_users else 0)
            + (1 if uid in error_users else 0)
        )
        sums[bucket] += slot_count

    for bucket, n in counts.items():
        if n > 0:
            averages[bucket] = round(sums[bucket] / n, 2)
    return counts, averages


def _triggered_user_ids(cohort_subq: Any, session: Any) -> set[int]:
    """Replicate the trigger SQL-side: ≥5 unresolved AND cooldown elapsed.

    Cooldown matches ``should_show_error_review`` — dynamic tiers via
    ``get_review_cooldown`` (3d default, 1d at ≥15 unresolved, 12h at ≥25).

    Uses a single subquery IN() to scan QuizErrorLog for the full cohort,
    then applies the time-based cooldown logic in Python.
    """
    now = datetime.now(timezone.utc)

    unresolved_expr = func.sum(
        case((QuizErrorLog.resolved_at.is_(None), 1), else_=0)
    ).label('unresolved')

    rows = (
        session.query(
            QuizErrorLog.user_id.label('uid'),
            unresolved_expr,
            func.max(QuizErrorLog.resolved_at).label('last_resolved'),
        )
        .filter(QuizErrorLog.user_id.in_(cohort_subq))
        .group_by(QuizErrorLog.user_id)
        .all()
    )

    triggered: set[int] = set()
    for row in rows:
        unresolved = int(row.unresolved or 0)
        if unresolved < REVIEW_TRIGGER_MIN_UNRESOLVED:
            continue
        last_resolved = row.last_resolved
        if last_resolved is None:
            triggered.add(int(row.uid))
            continue
        if last_resolved.tzinfo is None:
            last_resolved = last_resolved.replace(tzinfo=timezone.utc)
        if (now - last_resolved) >= get_review_cooldown(unresolved):
            triggered.add(int(row.uid))

    return triggered


def _error_review_trigger_rate(
    cohort_subq: Any, total: int, session: Any
) -> float:
    if not total:
        return 0.0
    triggered = _triggered_user_ids(cohort_subq, session)
    return round(len(triggered) / total * 100, 1)


def _error_review_qualified_user_ids(
    cohort_subq: Any,
    today: date,
    session: Any,
) -> set[int]:
    """Cohort users qualified for the error-review slot today.

    Counts users who had ≥ ``MIN_UNRESOLVED`` rows in their backlog at the
    *start of today*: rows that existed before today (``created_at < today``)
    and were either still unresolved or resolved during today. Rows created
    today are excluded — they were not part of the start-of-day backlog,
    even if they were resolved on the same day.

    Uses a single subquery IN() over the full cohort.
    """
    qualified: set[int] = set()
    rows = (
        session.query(
            QuizErrorLog.user_id,
            func.count().label('start_of_day'),
        )
        .filter(
            QuizErrorLog.user_id.in_(cohort_subq),
            func.date(QuizErrorLog.created_at) < today,
            case(
                (QuizErrorLog.resolved_at.is_(None), True),
                else_=func.date(QuizErrorLog.resolved_at) >= today,
            ),
        )
        .group_by(QuizErrorLog.user_id)
        .all()
    )
    for uid, start_of_day in rows:
        if int(start_of_day or 0) >= REVIEW_TRIGGER_MIN_UNRESOLVED:
            qualified.add(int(uid))
    return qualified


def _error_review_completion_rate(
    cohort_subq: Any,
    today: date,
    session: Any,
) -> float:
    """Fraction of qualified users who resolved at least one error today."""
    qualified = _error_review_qualified_user_ids(cohort_subq, today, session)
    if not qualified:
        return 0.0

    resolved_users: set[int] = set()
    for chunk in chunk_ids(list(qualified)):
        rows = (
            session.query(QuizErrorLog.user_id)
            .filter(
                QuizErrorLog.user_id.in_(chunk),
                QuizErrorLog.resolved_at.isnot(None),
                func.date(QuizErrorLog.resolved_at) == today,
                func.date(QuizErrorLog.created_at) < today,
            )
            .distinct()
            .all()
        )
        for row in rows:
            resolved_users.add(int(row[0]))

    return round(len(resolved_users) / len(qualified) * 100, 1)


def _reading_gate_completion_rate(
    cohort_subq: Any, total: int, today: date, session: Any
) -> float:
    """Fraction of cohort that earned ``linear_book_reading`` XP today.

    The XP idempotency record is the canonical signal that the reading
    gate (≥5% chapter delta AND ≥60s reading time) was satisfied at least
    once today.
    """
    if not total:
        return 0.0

    from app.achievements.models import StreakEvent

    completed = (
        session.query(func.count(func.distinct(StreakEvent.user_id)))
        .filter(
            StreakEvent.user_id.in_(cohort_subq),
            StreakEvent.event_type == 'xp_linear',
            StreakEvent.event_date == today,
            StreakEvent.details['source'].astext == 'linear_book_reading',
        )
        .scalar()
        or 0
    )
    return round(completed / total * 100, 1)


def _book_select_rate(cohort_subq: Any, total: int, session: Any) -> float:
    if not total:
        return 0.0
    selected = (
        session.query(func.count(UserReadingPreference.user_id))
        .filter(UserReadingPreference.user_id.in_(cohort_subq))
        .scalar()
        or 0
    )
    return round(selected / total * 100, 1)


def get_linear_plan_metrics(session: Any = None, today: Optional[date] = None) -> dict:
    """Aggregate linear-plan metrics for the admin dashboard.

    Returns a dict with ratios plus ``cohort_size`` for context. All
    ratios default to 0.0 when the cohort is empty so the dashboard
    template can render unconditionally.

    All queries use a cohort subquery (``SELECT id FROM users WHERE
    use_linear_plan = TRUE``) so query count is O(1), not O(cohort / 1000).
    """
    s = session if session is not None else db.session
    eval_date = today if today is not None else _today_utc()

    cohort_subq = _cohort_subquery(s)
    total = _cohort_size(s)

    if total == 0:
        empty: dict[str, int] = {b: 0 for b in FOCUS_BUCKETS}
        empty_avg: dict[str, float] = {b: 0.0 for b in FOCUS_BUCKETS}
        return {
            'cohort_size': 0,
            'day_secured_rate': 0.0,
            'average_slots_completed': 0.0,
            'error_review_trigger_rate': 0.0,
            'error_review_completion_rate': 0.0,
            'book_select_rate': 0.0,
            'reading_gate_completion_rate': 0.0,
            'focus_distribution': empty,
            'focus_average_slots': empty_avg,
        }

    active_sets = _active_user_sets(cohort_subq, eval_date, s)
    focus_counts, focus_avg_slots = _focus_distribution_and_avg_slots(
        cohort_subq, eval_date, s, active_sets=active_sets
    )

    return {
        'cohort_size': total,
        'day_secured_rate': _day_secured_rate(cohort_subq, total, eval_date, s),
        'average_slots_completed': _average_slots_completed(total, active_sets),
        'error_review_trigger_rate': _error_review_trigger_rate(cohort_subq, total, s),
        'error_review_completion_rate': _error_review_completion_rate(
            cohort_subq, eval_date, s
        ),
        'book_select_rate': _book_select_rate(cohort_subq, total, s),
        'reading_gate_completion_rate': _reading_gate_completion_rate(
            cohort_subq, total, eval_date, s
        ),
        'focus_distribution': focus_counts,
        'focus_average_slots': focus_avg_slots,
    }
