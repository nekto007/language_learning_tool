# app/admin/services/cohort_service.py

"""Conversion funnel and cohort retention analytics."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import exists, func, or_

logger = logging.getLogger(__name__)


@dataclass
class FunnelStep:
    key: str
    label: str
    count: int
    conversion_from_prev: Optional[float]
    conversion_from_top: Optional[float]


@dataclass
class FunnelData:
    steps: List[FunnelStep]
    days: int
    generated_at: datetime


@dataclass
class CohortWeek:
    week_label: str
    week_start: str
    cohort_size: int
    day1_pct: Optional[float]
    day7_pct: Optional[float]
    day30_pct: Optional[float]


def get_funnel_data(db_session: Any, days: int = 30) -> FunnelData:
    """Return conversion funnel counts for users registered in the last `days` days."""
    from app.auth.models import User
    from app.curriculum.models import LessonProgress
    from app.daily_plan.models import DailyPlanLog

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    _min_offset = timedelta(hours=1)
    _delta_7 = timedelta(days=7)
    _delta_30 = timedelta(days=30)

    registered = int(
        db_session.query(func.count(User.id))
        .filter(User.created_at >= cutoff, User.is_admin.is_(False))
        .scalar() or 0
    )

    onboarding = int(
        db_session.query(func.count(User.id))
        .filter(
            User.created_at >= cutoff,
            User.is_admin.is_(False),
            User.onboarding_completed.is_(True),
        )
        .scalar() or 0
    )

    first_plan = int(
        db_session.query(func.count(User.id.distinct()))
        .filter(
            User.created_at >= cutoff,
            User.is_admin.is_(False),
            exists().where(DailyPlanLog.user_id == User.id),
        )
        .scalar() or 0
    )

    day_secured_count = int(
        db_session.query(func.count(User.id.distinct()))
        .filter(
            User.created_at >= cutoff,
            User.is_admin.is_(False),
            exists().where(
                (DailyPlanLog.user_id == User.id)
                & DailyPlanLog.secured_at.isnot(None)
            ),
        )
        .scalar() or 0
    )

    retention_7 = _count_retained(db_session, cutoff, _delta_7, _min_offset, LessonProgress)
    retention_30 = _count_retained(db_session, cutoff, _delta_30, _min_offset, LessonProgress)

    raw = [
        ('registered', 'Зарегистрировались', registered),
        ('onboarding_completed', 'Прошли онбординг', onboarding),
        ('first_plan_built', 'Построили план', first_plan),
        ('day_secured', 'Закрыли день', day_secured_count),
        ('retention_7d', 'Активны на 7-й день', retention_7),
        ('retention_30d', 'Активны на 30-й день', retention_30),
    ]

    steps: List[FunnelStep] = []
    top = registered or 1
    prev = None
    for key, label, count in raw:
        conv_prev = round(count / prev * 100, 1) if prev else None
        conv_top = round(count / top * 100, 1)
        steps.append(FunnelStep(
            key=key,
            label=label,
            count=count,
            conversion_from_prev=conv_prev,
            conversion_from_top=conv_top,
        ))
        prev = max(count, 1)

    return FunnelData(steps=steps, days=days, generated_at=now)


def _count_retained(
    db_session: Any,
    cutoff: datetime,
    delta: timedelta,
    min_offset: timedelta,
    lesson_progress_cls: Any,
) -> int:
    """Count cohort users with activity in [min_offset, delta] after registration."""
    from app.auth.models import User
    from app.daily_plan.models import DailyPlanLog

    return int(
        db_session.query(func.count(User.id.distinct()))
        .filter(
            User.created_at >= cutoff,
            User.is_admin.is_(False),
            or_(
                exists().where(
                    (DailyPlanLog.user_id == User.id)
                    & (DailyPlanLog.created_at >= User.created_at + min_offset)
                    & (DailyPlanLog.created_at <= User.created_at + delta)
                ),
                exists().where(
                    (lesson_progress_cls.user_id == User.id)
                    & (lesson_progress_cls.last_activity >= User.created_at + min_offset)
                    & (lesson_progress_cls.last_activity <= User.created_at + delta)
                ),
            ),
        )
        .scalar() or 0
    )


def get_cohort_retention(db_session: Any, weeks: int = 8) -> List[CohortWeek]:
    """Return weekly cohort retention matrix for the last `weeks` weeks."""
    from app.auth.models import User
    from app.curriculum.models import LessonProgress
    from app.daily_plan.models import DailyPlanLog

    now = datetime.now(timezone.utc)
    today = now.date()
    monday_this_week = today - timedelta(days=today.weekday())
    # weeks-1 so the last bucket is the current (incomplete) week
    range_start = monday_this_week - timedelta(weeks=weeks - 1)
    range_start_dt = datetime(range_start.year, range_start.month, range_start.day, tzinfo=timezone.utc)

    user_rows = (
        db_session.query(User.id, User.created_at)
        .filter(
            User.created_at >= range_start_dt,
            User.is_admin.is_(False),
        )
        .all()
    )

    if not user_rows:
        return [
            CohortWeek(
                week_label=_format_week(range_start + timedelta(weeks=w)),
                week_start=(range_start + timedelta(weeks=w)).isoformat(),
                cohort_size=0,
                day1_pct=None,
                day7_pct=None,
                day30_pct=None,
            )
            for w in range(weeks)  # w=0..weeks-1 → oldest..current week
        ]

    all_user_ids = [r[0] for r in user_rows]

    # Fetch DailyPlanLog timestamps per user (created_at = plan was built)
    plan_ts: Dict[int, List[datetime]] = {}
    for chunk_start in range(0, len(all_user_ids), 1000):
        chunk = all_user_ids[chunk_start:chunk_start + 1000]
        for uid, ts in db_session.query(DailyPlanLog.user_id, DailyPlanLog.created_at).filter(
            DailyPlanLog.user_id.in_(chunk)
        ).all():
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts:
                plan_ts.setdefault(uid, []).append(ts)

    # Fetch LessonProgress.last_activity per user
    lesson_ts: Dict[int, List[datetime]] = {}
    for chunk_start in range(0, len(all_user_ids), 1000):
        chunk = all_user_ids[chunk_start:chunk_start + 1000]
        for uid, ts in db_session.query(LessonProgress.user_id, LessonProgress.last_activity).filter(
            LessonProgress.user_id.in_(chunk),
            LessonProgress.last_activity.isnot(None),
        ).all():
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts:
                lesson_ts.setdefault(uid, []).append(ts)

    def had_activity(user_id: int, reg_ts: datetime, min_hours: float, max_hours: float) -> bool:
        w_start = reg_ts + timedelta(hours=min_hours)
        w_end = reg_ts + timedelta(hours=max_hours)
        for ts in plan_ts.get(user_id, []):
            if w_start <= ts <= w_end:
                return True
        for ts in lesson_ts.get(user_id, []):
            if w_start <= ts <= w_end:
                return True
        return False

    # Group users into weekly cohorts
    week_buckets: Dict[str, list] = {}
    for user_id, created_at in user_rows:
        if created_at is None:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        d = created_at.date()
        monday = d - timedelta(days=d.weekday())
        key = monday.isoformat()
        week_buckets.setdefault(key, []).append((user_id, created_at))

    result: List[CohortWeek] = []
    for w in range(weeks):
        week_start = range_start + timedelta(weeks=w)
        week_end = week_start + timedelta(weeks=1)
        key = week_start.isoformat()
        users = week_buckets.get(key, [])
        size = len(users)

        if size == 0:
            result.append(CohortWeek(
                week_label=_format_week(week_start),
                week_start=key,
                cohort_size=0,
                day1_pct=None,
                day7_pct=None,
                day30_pct=None,
            ))
            continue

        week_end_dt = datetime(week_end.year, week_end.month, week_end.day, tzinfo=timezone.utc)
        days_since_week_end = (now - week_end_dt).days

        day1_count = sum(1 for uid, reg in users if had_activity(uid, reg, 1, 48))
        day1_pct = round(day1_count / size * 100, 1)

        day7_pct = None
        if days_since_week_end >= 7:
            c = sum(1 for uid, reg in users if had_activity(uid, reg, 1, 168))
            day7_pct = round(c / size * 100, 1)

        day30_pct = None
        if days_since_week_end >= 30:
            c = sum(1 for uid, reg in users if had_activity(uid, reg, 1, 720))
            day30_pct = round(c / size * 100, 1)

        result.append(CohortWeek(
            week_label=_format_week(week_start),
            week_start=key,
            cohort_size=size,
            day1_pct=day1_pct,
            day7_pct=day7_pct,
            day30_pct=day30_pct,
        ))

    return result


def _format_week(monday) -> str:
    sunday = monday + timedelta(days=6)
    months = ['', 'янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек']
    return f'{monday.day} {months[monday.month]} – {sunday.day} {months[sunday.month]}'
