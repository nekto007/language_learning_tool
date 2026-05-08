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
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import case, func

from app.auth.models import User
from app.books.models import UserChapterProgress
from app.curriculum.models import LessonProgress
from app.daily_plan.linear.errors import REVIEW_TRIGGER_COOLDOWN, REVIEW_TRIGGER_MIN_UNRESOLVED
from app.daily_plan.linear.models import QuizErrorLog, UserReadingPreference
from app.daily_plan.models import DailyPlanLog
from app.study.models import StudySession
from app.utils.db import db
from app.utils.db_utils import chunk_ids


def _cohort_user_ids(session: Any = None) -> list[int]:
    """Return all user ids that currently have the linear plan enabled."""
    s = session if session is not None else db.session
    rows = s.query(User.id).filter(User.use_linear_plan.is_(True)).all()
    return [row[0] for row in rows]


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _day_secured_rate(user_ids: list[int], today: date, session: Any) -> float:
    if not user_ids:
        return 0.0
    secured = 0
    for chunk in chunk_ids(user_ids):
        secured += (
            session.query(func.count(DailyPlanLog.id))
            .filter(
                DailyPlanLog.user_id.in_(chunk),
                DailyPlanLog.plan_date == today,
                DailyPlanLog.secured_at.isnot(None),
            )
            .scalar()
            or 0
        )
    return round(secured / len(user_ids) * 100, 1)


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


def _per_user_slot_counts(user_ids: list[int], today: date, session: Any) -> dict[int, int]:
    """Return ``{user_id: slot_count}`` for activity-completed slots today.

    Uses the same proxy signals as ``_average_slots_completed`` (curriculum
    completion, study session, reading-progress update, error resolved).
    """
    if not user_ids:
        return {}

    curriculum_users: set[int] = set()
    srs_users: set[int] = set()
    reading_users: set[int] = set()
    error_users: set[int] = set()

    for chunk in chunk_ids(user_ids):
        for row in (
            session.query(LessonProgress.user_id)
            .filter(
                LessonProgress.user_id.in_(chunk),
                LessonProgress.status == 'completed',
                func.date(LessonProgress.completed_at) == today,
            )
            .distinct()
            .all()
        ):
            curriculum_users.add(row[0])

        for row in (
            session.query(StudySession.user_id)
            .filter(
                StudySession.user_id.in_(chunk),
                func.date(StudySession.start_time) == today,
            )
            .distinct()
            .all()
        ):
            srs_users.add(row[0])

        for row in (
            session.query(UserChapterProgress.user_id)
            .filter(
                UserChapterProgress.user_id.in_(chunk),
                UserChapterProgress.updated_at.isnot(None),
                func.date(UserChapterProgress.updated_at) == today,
            )
            .distinct()
            .all()
        ):
            reading_users.add(row[0])

        # Error-review completion proxy: a resolved_at stamped today.
        for row in (
            session.query(QuizErrorLog.user_id)
            .filter(
                QuizErrorLog.user_id.in_(chunk),
                QuizErrorLog.resolved_at.isnot(None),
                func.date(QuizErrorLog.resolved_at) == today,
            )
            .distinct()
            .all()
        ):
            error_users.add(row[0])

    counts: dict[int, int] = {}
    for uid in user_ids:
        slots = 0
        if uid in curriculum_users:
            slots += 1
        if uid in srs_users:
            slots += 1
        if uid in reading_users:
            slots += 1
        if uid in error_users:
            slots += 1
        counts[uid] = slots
    return counts


def _average_slots_completed(user_ids: list[int], today: date, session: Any) -> float:
    """Proxy: count activity-completed baseline slots per user, average."""
    if not user_ids:
        return 0.0
    counts = _per_user_slot_counts(user_ids, today, session)
    total = sum(counts.values())
    return round(total / len(user_ids), 2)


def _focus_distribution_and_avg_slots(
    user_ids: list[int], today: date, session: Any
) -> tuple[dict[str, int], dict[str, float]]:
    """Return (counts_per_focus, avg_slots_per_focus) over the cohort."""
    counts: dict[str, int] = {bucket: 0 for bucket in FOCUS_BUCKETS}
    sums: dict[str, int] = {bucket: 0 for bucket in FOCUS_BUCKETS}
    averages: dict[str, float] = {bucket: 0.0 for bucket in FOCUS_BUCKETS}

    if not user_ids:
        return counts, averages

    user_focus: dict[int, str] = {}
    for chunk in chunk_ids(user_ids):
        rows = (
            session.query(User.id, User.onboarding_focus)
            .filter(User.id.in_(chunk))
            .all()
        )
        for uid, raw in rows:
            user_focus[int(uid)] = _classify_focus(raw)

    slot_counts = _per_user_slot_counts(user_ids, today, session)

    for uid in user_ids:
        bucket = user_focus.get(uid, 'none')
        counts[bucket] += 1
        sums[bucket] += slot_counts.get(uid, 0)

    for bucket, n in counts.items():
        if n > 0:
            averages[bucket] = round(sums[bucket] / n, 2)
    return counts, averages


def _triggered_user_ids(user_ids: list[int], session: Any) -> set[int]:
    """Replicate the trigger SQL-side: ≥5 unresolved AND cooldown elapsed."""
    if not user_ids:
        return set()

    cooldown_cutoff = datetime.now(timezone.utc) - REVIEW_TRIGGER_COOLDOWN

    unresolved_expr = func.sum(
        case((QuizErrorLog.resolved_at.is_(None), 1), else_=0)
    ).label('unresolved')

    per_user = []
    for chunk in chunk_ids(user_ids):
        per_user.extend(
            session.query(
                QuizErrorLog.user_id.label('uid'),
                unresolved_expr,
                func.max(QuizErrorLog.resolved_at).label('last_resolved'),
            )
            .filter(QuizErrorLog.user_id.in_(chunk))
            .group_by(QuizErrorLog.user_id)
            .all()
        )

    triggered: set[int] = set()
    for row in per_user:
        unresolved = int(row.unresolved or 0)
        if unresolved < REVIEW_TRIGGER_MIN_UNRESOLVED:
            continue
        last_resolved = row.last_resolved
        if last_resolved is None:
            triggered.add(int(row.uid))
            continue
        if last_resolved.tzinfo is None:
            last_resolved = last_resolved.replace(tzinfo=timezone.utc)
        if last_resolved <= cooldown_cutoff:
            triggered.add(int(row.uid))

    return triggered


def _error_review_trigger_rate(user_ids: list[int], session: Any) -> float:
    if not user_ids:
        return 0.0
    triggered = _triggered_user_ids(user_ids, session)
    return round(len(triggered) / len(user_ids) * 100, 1)


def _error_review_qualified_user_ids(user_ids: list[int], session: Any) -> set[int]:
    """Cohort users with ≥REVIEW_TRIGGER_MIN_UNRESOLVED unresolved errors."""
    if not user_ids:
        return set()
    qualified: set[int] = set()
    for chunk in chunk_ids(user_ids):
        rows = (
            session.query(
                QuizErrorLog.user_id,
                func.count(QuizErrorLog.id).label('unresolved'),
            )
            .filter(
                QuizErrorLog.user_id.in_(chunk),
                QuizErrorLog.resolved_at.is_(None),
            )
            .group_by(QuizErrorLog.user_id)
            .having(func.count(QuizErrorLog.id) >= REVIEW_TRIGGER_MIN_UNRESOLVED)
            .all()
        )
        for row in rows:
            qualified.add(int(row[0]))
    return qualified


def _error_review_completion_rate(
    user_ids: list[int],
    today: date,
    session: Any,
) -> float:
    """Fraction of qualified users who resolved at least one error today."""
    if not user_ids:
        return 0.0
    qualified = _error_review_qualified_user_ids(user_ids, session)
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
            )
            .distinct()
            .all()
        )
        for row in rows:
            resolved_users.add(int(row[0]))

    return round(len(resolved_users) / len(qualified) * 100, 1)


def _reading_gate_completion_rate(
    user_ids: list[int], today: date, session: Any
) -> float:
    """Fraction of cohort that earned ``linear_book_reading`` XP today.

    The XP idempotency record is the canonical signal that the reading
    gate (≥5% chapter delta AND ≥60s reading time) was satisfied at least
    once today.
    """
    if not user_ids:
        return 0.0

    from app.achievements.models import StreakEvent

    completed = 0
    for chunk in chunk_ids(user_ids):
        rows = (
            session.query(StreakEvent.user_id)
            .filter(
                StreakEvent.user_id.in_(chunk),
                StreakEvent.event_type == 'xp_linear',
                StreakEvent.event_date == today,
                StreakEvent.details['source'].astext == 'linear_book_reading',
            )
            .distinct()
            .all()
        )
        completed += len(rows)
    return round(completed / len(user_ids) * 100, 1)


def _book_select_rate(user_ids: list[int], session: Any) -> float:
    if not user_ids:
        return 0.0
    selected = 0
    for chunk in chunk_ids(user_ids):
        selected += (
            session.query(func.count(UserReadingPreference.user_id))
            .filter(UserReadingPreference.user_id.in_(chunk))
            .scalar()
            or 0
        )
    return round(selected / len(user_ids) * 100, 1)


def get_linear_plan_metrics(session: Any = None, today: Optional[date] = None) -> dict:
    """Aggregate linear-plan metrics for the admin dashboard.

    Returns a dict with four ratios plus ``cohort_size`` for context. All
    ratios default to 0.0 when the cohort is empty so the dashboard
    template can render unconditionally.
    """
    s = session if session is not None else db.session
    eval_date = today if today is not None else _today_utc()
    user_ids = _cohort_user_ids(s)
    focus_counts, focus_avg_slots = _focus_distribution_and_avg_slots(user_ids, eval_date, s)

    return {
        'cohort_size': len(user_ids),
        'day_secured_rate': _day_secured_rate(user_ids, eval_date, s),
        'average_slots_completed': _average_slots_completed(user_ids, eval_date, s),
        'error_review_trigger_rate': _error_review_trigger_rate(user_ids, s),
        'error_review_completion_rate': _error_review_completion_rate(user_ids, eval_date, s),
        'book_select_rate': _book_select_rate(user_ids, s),
        'reading_gate_completion_rate': _reading_gate_completion_rate(user_ids, eval_date, s),
        'focus_distribution': focus_counts,
        'focus_average_slots': focus_avg_slots,
    }
