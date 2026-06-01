# app/admin/services/activity_feed_service.py

"""Activity feed service — aggregates events from multiple sources for the admin activity view."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)


EVENT_TYPE_LABELS = {
    'lesson_completed': 'Урок завершён',
    'achievement_granted': 'Достижение получено',
    'xp_awarded': 'XP начислен',
    'day_secured': 'День закрыт',
    'admin_action': 'Действие администратора',
}

ALL_EVENT_TYPES = list(EVENT_TYPE_LABELS.keys())


@dataclass
class ActivityEvent:
    timestamp: datetime
    user_id: Optional[int]
    user_email: Optional[str]
    event_type: str
    description: str
    detail_url: Optional[str] = None


def get_recent_events(
    db_session,
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[int] = None,
    event_types: Optional[List[str]] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> List[ActivityEvent]:
    """Aggregate recent events from multiple tables, newest first.

    Fetches from each applicable source up to (offset + limit) rows,
    merges in Python, and applies final offset/limit slice.
    """
    if event_types is None:
        event_types = ALL_EVENT_TYPES

    # Fetch enough from each source to satisfy offset + limit after merge
    max_per_source = offset + limit

    all_events: List[ActivityEvent] = []

    try:
        if 'lesson_completed' in event_types:
            all_events.extend(
                _fetch_lesson_completed(db_session, user_id, date_from, date_to, max_per_source)
            )
    except Exception:
        logger.exception('Failed to fetch lesson_completed events')

    try:
        if 'achievement_granted' in event_types:
            all_events.extend(
                _fetch_achievements(db_session, user_id, date_from, date_to, max_per_source)
            )
    except Exception:
        logger.exception('Failed to fetch achievement_granted events')

    try:
        if 'xp_awarded' in event_types:
            all_events.extend(
                _fetch_xp_events(db_session, user_id, date_from, date_to, max_per_source)
            )
    except Exception:
        logger.exception('Failed to fetch xp_awarded events')

    try:
        if 'day_secured' in event_types:
            all_events.extend(
                _fetch_day_secured(db_session, user_id, date_from, date_to, max_per_source)
            )
    except Exception:
        logger.exception('Failed to fetch day_secured events')

    try:
        if 'admin_action' in event_types:
            all_events.extend(
                _fetch_admin_actions(db_session, user_id, date_from, date_to, max_per_source)
            )
    except Exception:
        logger.exception('Failed to fetch admin_action events')

    all_events.sort(key=lambda e: e.timestamp if e.timestamp else datetime.min, reverse=True)
    return all_events[offset: offset + limit]


# ---------------------------------------------------------------------------
# Private fetch helpers
# ---------------------------------------------------------------------------

def _fetch_lesson_completed(db_session, user_id, date_from, date_to, limit) -> List[ActivityEvent]:
    from app.auth.models import User
    from app.curriculum.models import LessonProgress, Lessons

    q = (
        db_session.query(LessonProgress, User, Lessons)
        .join(User, User.id == LessonProgress.user_id)
        .outerjoin(Lessons, Lessons.id == LessonProgress.lesson_id)
        .filter(LessonProgress.status == 'completed')
        .filter(LessonProgress.completed_at.isnot(None))
    )
    if user_id is not None:
        q = q.filter(LessonProgress.user_id == user_id)
    if date_from:
        q = q.filter(LessonProgress.completed_at >= date_from)
    if date_to:
        q = q.filter(LessonProgress.completed_at < date_to + timedelta(days=1))
    q = q.order_by(LessonProgress.completed_at.desc()).limit(limit)

    events = []
    for lp, user, lesson in q:
        score_str = f', {int(round(lp.score))}%' if lp.score is not None else ''
        lesson_title = lesson.title if lesson else f'#{lp.lesson_id} (удалён)'
        events.append(ActivityEvent(
            timestamp=lp.completed_at,
            user_id=user.id,
            user_email=user.email,
            event_type='lesson_completed',
            description=f'Завершил урок «{lesson_title}»{score_str}',
        ))
    return events


def _fetch_achievements(db_session, user_id, date_from, date_to, limit) -> List[ActivityEvent]:
    from app.auth.models import User
    from app.study.models import Achievement, UserAchievement

    q = (
        db_session.query(UserAchievement, User, Achievement)
        .join(User, User.id == UserAchievement.user_id)
        .outerjoin(Achievement, Achievement.id == UserAchievement.achievement_id)
    )
    if user_id is not None:
        q = q.filter(UserAchievement.user_id == user_id)
    if date_from:
        q = q.filter(UserAchievement.earned_at >= date_from)
    if date_to:
        q = q.filter(UserAchievement.earned_at < date_to + timedelta(days=1))
    q = q.order_by(UserAchievement.earned_at.desc()).limit(limit)

    events = []
    for ua, user, ach in q:
        ach_name = ach.name if ach else f'#{ua.achievement_id} (удалён)'
        events.append(ActivityEvent(
            timestamp=ua.earned_at,
            user_id=user.id,
            user_email=user.email,
            event_type='achievement_granted',
            description=f'Получил достижение «{ach_name}»',
        ))
    return events


def _fetch_xp_events(db_session, user_id, date_from, date_to, limit) -> List[ActivityEvent]:
    from app.achievements.models import StreakEvent
    from app.auth.models import User

    q = (
        db_session.query(StreakEvent, User)
        .join(User, User.id == StreakEvent.user_id)
        .filter(StreakEvent.event_type.like('xp_%'))
    )
    if user_id is not None:
        q = q.filter(StreakEvent.user_id == user_id)
    if date_from:
        q = q.filter(StreakEvent.created_at >= date_from)
    if date_to:
        q = q.filter(StreakEvent.created_at < date_to + timedelta(days=1))
    q = q.order_by(StreakEvent.created_at.desc()).limit(limit)

    events = []
    for se, user in q:
        # Unified XP write-paths store the awarded amount in details['xp'];
        # coins_delta is always 0 for xp_* events.
        details = se.details or {}
        xp_amount = details.get('xp') or se.coins_delta or 0
        label = se.event_type.replace('xp_', '').replace('_', ' ')
        events.append(ActivityEvent(
            timestamp=se.created_at,
            user_id=user.id,
            user_email=user.email,
            event_type='xp_awarded',
            description=f'+{xp_amount} XP ({label})',
        ))
    return events


def _fetch_day_secured(db_session, user_id, date_from, date_to, limit) -> List[ActivityEvent]:
    from app.auth.models import User
    from app.daily_plan.models import DailyPlanLog

    q = (
        db_session.query(DailyPlanLog, User)
        .join(User, User.id == DailyPlanLog.user_id)
        .filter(DailyPlanLog.secured_at.isnot(None))
    )
    if user_id is not None:
        q = q.filter(DailyPlanLog.user_id == user_id)
    if date_from:
        q = q.filter(DailyPlanLog.secured_at >= date_from)
    if date_to:
        q = q.filter(DailyPlanLog.secured_at < date_to + timedelta(days=1))
    q = q.order_by(DailyPlanLog.secured_at.desc()).limit(limit)

    events = []
    for log, user in q:
        mission_str = f' ({log.mission_type})' if log.mission_type else ''
        events.append(ActivityEvent(
            timestamp=log.secured_at,
            user_id=user.id,
            user_email=user.email,
            event_type='day_secured',
            description=f'День закрыт{mission_str} ({log.plan_date})',
        ))
    return events


def _fetch_admin_actions(db_session, user_id, date_from, date_to, limit) -> List[ActivityEvent]:
    from app.admin.audit import AdminAuditLog
    from app.auth.models import User

    q = (
        db_session.query(AdminAuditLog, User)
        .join(User, User.id == AdminAuditLog.admin_id, isouter=True)
    )
    # user_id filter applies to admin_id for admin_action events
    if user_id is not None:
        q = q.filter(AdminAuditLog.admin_id == user_id)
    if date_from:
        q = q.filter(AdminAuditLog.created_at >= date_from)
    if date_to:
        q = q.filter(AdminAuditLog.created_at < date_to + timedelta(days=1))
    q = q.order_by(AdminAuditLog.created_at.desc()).limit(limit)

    events = []
    for log, admin_user in q:
        email = admin_user.email if admin_user else f'admin#{log.admin_id}'
        target_str = ''
        if log.target_type:
            target_str = f' → {log.target_type}'
            if log.target_id:
                target_str += f'#{log.target_id}'
        events.append(ActivityEvent(
            timestamp=log.created_at,
            user_id=log.admin_id,
            user_email=email,
            event_type='admin_action',
            description=f'{log.action}{target_str}',
        ))
    return events
