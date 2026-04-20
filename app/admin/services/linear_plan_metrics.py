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
    secured = (
        session.query(func.count(DailyPlanLog.id))
        .filter(
            DailyPlanLog.user_id.in_(user_ids),
            DailyPlanLog.plan_date == today,
            DailyPlanLog.secured_at.isnot(None),
        )
        .scalar()
        or 0
    )
    return round(secured / len(user_ids) * 100, 1)


def _average_slots_completed(user_ids: list[int], today: date, session: Any) -> float:
    """Proxy: count activity-completed baseline slots per user, average."""
    if not user_ids:
        return 0.0

    curriculum_rows = (
        session.query(LessonProgress.user_id)
        .filter(
            LessonProgress.user_id.in_(user_ids),
            LessonProgress.status == 'completed',
            func.date(LessonProgress.completed_at) == today,
        )
        .distinct()
        .all()
    )
    curriculum_users = {row[0] for row in curriculum_rows}

    srs_rows = (
        session.query(StudySession.user_id)
        .filter(
            StudySession.user_id.in_(user_ids),
            func.date(StudySession.start_time) == today,
        )
        .distinct()
        .all()
    )
    srs_users = {row[0] for row in srs_rows}

    reading_rows = (
        session.query(UserChapterProgress.user_id)
        .filter(
            UserChapterProgress.user_id.in_(user_ids),
            UserChapterProgress.updated_at.isnot(None),
            func.date(UserChapterProgress.updated_at) == today,
        )
        .distinct()
        .all()
    )
    reading_users = {row[0] for row in reading_rows}

    # Error-review completion proxy: a resolved_at stamped today.
    error_rows = (
        session.query(QuizErrorLog.user_id)
        .filter(
            QuizErrorLog.user_id.in_(user_ids),
            QuizErrorLog.resolved_at.isnot(None),
            func.date(QuizErrorLog.resolved_at) == today,
        )
        .distinct()
        .all()
    )
    error_users = {row[0] for row in error_rows}

    total = 0
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
        total += slots
    return round(total / len(user_ids), 2)


def _error_review_trigger_rate(user_ids: list[int], session: Any) -> float:
    """Replicate the trigger SQL-side: ≥5 unresolved AND cooldown elapsed."""
    if not user_ids:
        return 0.0

    cooldown_cutoff = datetime.now(timezone.utc) - REVIEW_TRIGGER_COOLDOWN

    unresolved_expr = func.sum(
        case((QuizErrorLog.resolved_at.is_(None), 1), else_=0)
    ).label('unresolved')

    per_user = (
        session.query(
            QuizErrorLog.user_id.label('uid'),
            unresolved_expr,
            func.max(QuizErrorLog.resolved_at).label('last_resolved'),
        )
        .filter(QuizErrorLog.user_id.in_(user_ids))
        .group_by(QuizErrorLog.user_id)
        .all()
    )

    triggered = 0
    for row in per_user:
        unresolved = int(row.unresolved or 0)
        if unresolved < REVIEW_TRIGGER_MIN_UNRESOLVED:
            continue
        last_resolved = row.last_resolved
        if last_resolved is None:
            triggered += 1
            continue
        if last_resolved.tzinfo is None:
            last_resolved = last_resolved.replace(tzinfo=timezone.utc)
        if last_resolved <= cooldown_cutoff:
            triggered += 1

    return round(triggered / len(user_ids) * 100, 1)


def _book_select_rate(user_ids: list[int], session: Any) -> float:
    if not user_ids:
        return 0.0
    selected = (
        session.query(func.count(UserReadingPreference.user_id))
        .filter(UserReadingPreference.user_id.in_(user_ids))
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

    return {
        'cohort_size': len(user_ids),
        'day_secured_rate': _day_secured_rate(user_ids, eval_date, s),
        'average_slots_completed': _average_slots_completed(user_ids, eval_date, s),
        'error_review_trigger_rate': _error_review_trigger_rate(user_ids, s),
        'book_select_rate': _book_select_rate(user_ids, s),
    }
