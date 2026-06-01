"""Notification creation service."""
import logging
from datetime import datetime

from app.notifications.models import Notification
from app.utils.db import db

logger = logging.getLogger(__name__)

# Map notification types to User preference field names
_PREF_MAP = {
    'achievement': 'notify_in_app_achievements',
    'level_up': 'notify_in_app_achievements',
    'rank_up': 'notify_in_app_achievements',
    'streak_milestone': 'notify_in_app_streaks',
    'plan_streak_milestone': 'notify_in_app_achievements',
    'weekly_challenge': 'notify_in_app_weekly',
    'referral': None,  # always send referral notifications
}

PLAN_STREAK_MILESTONE_DAYS = {7, 30, 100}


def _user_allows(user_id: int, notif_type: str) -> bool:
    """Check whether user's notification preferences allow this type."""
    pref_field = _PREF_MAP.get(notif_type)
    if pref_field is None:
        return True  # no preference gate for this type
    try:
        from app.auth.models import User
        user = User.query.get(user_id)
        if user is None:
            return True
        return getattr(user, pref_field, True)
    except Exception:
        logger.exception("Failed to check notification preference for user %s", user_id)
        return True  # fail open — don't break callers


def create_notification(user_id: int, type: str, title: str,
                        message: str = '', link: str = '', icon: str = '🔔') -> Notification | None:
    """Create a notification for a user, respecting their preferences."""
    if not _user_allows(user_id, type):
        return None

    notif = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        link=link,
        icon=icon,
    )
    db.session.add(notif)
    return notif


def notify_achievement(user_id: int, achievement_name: str, achievement_icon: str = '🏆') -> Notification:
    return create_notification(
        user_id, 'achievement',
        title=f'Новое достижение: {achievement_name}',
        icon=achievement_icon,
        link='/study/stats',
    )


def notify_level_up(user_id: int, new_level: int) -> Notification | None:
    """Create a level-up notification, deduplicating per level per day.

    Multiple concurrent XP awards that both trigger the same level-up will
    produce at most one notification row.
    """
    from datetime import timezone as _tz
    title = f'Уровень {new_level}!'
    day_start = (
        datetime.now(_tz.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .replace(tzinfo=None)
    )
    existing = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.type == 'level_up',
        Notification.title == title,
        Notification.created_at >= day_start,
    ).first()
    if existing:
        return existing
    return create_notification(
        user_id, 'level_up',
        title=title,
        message='Поздравляем с новым уровнем!',
        icon='🎉',
        link='/dashboard',
    )


def notify_rank_up(user_id: int, rank_name: str) -> Notification | None:
    return create_notification(
        user_id, 'rank_up',
        title=f'Новый титул: {rank_name}!',
        message='Ты поднялся на новый уровень ежедневного плана',
        icon='🎖️',
        link='/dashboard',
    )


def notify_streak_milestone(user_id: int, streak: int, reward: int) -> Notification:
    return create_notification(
        user_id, 'streak_milestone',
        title=f'Стрик {streak} дней!',
        message=f'+{reward} монет за достижение',
        icon='🔥',
        link='/dashboard',
    )


def notify_plan_streak_milestone(user_id: int, streak: int) -> Notification | None:
    return create_notification(
        user_id, 'plan_streak_milestone',
        title=f'Серия {streak} дней!',
        message='День завершён — серия продолжается',
        icon='🔥',
        link='/dashboard',
    )


def check_plan_streak_milestone_notification(
    user_id: int, current_streak: int, plan_date,
) -> None:
    """Create a plan_streak_milestone notification if streak hits 7/30/100 days.

    Deduplicates per calendar day — safe to call from multiple day-secured paths.
    Respects user's notify_in_app_achievements preference via create_notification.
    """
    if current_streak not in PLAN_STREAK_MILESTONE_DAYS:
        return
    # Notification.created_at stores naive UTC; dedup against UTC midnight.
    from datetime import timezone as _tz
    day_start = datetime.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0).replace(tzinfo=None)
    existing = Notification.query.filter(
        Notification.user_id == user_id,
        Notification.type == 'plan_streak_milestone',
        Notification.created_at >= day_start,
    ).first()
    if existing:
        return
    notify_plan_streak_milestone(user_id, current_streak)


def notify_referral(user_id: int, referred_username: str, bonus_xp: int | None = None) -> Notification:
    if bonus_xp is None:
        from app.admin.site_settings import get_referral_bonus_xp
        bonus_xp = get_referral_bonus_xp()
    return create_notification(
        user_id, 'referral',
        title=f'{referred_username} присоединился!',
        message=f'+{bonus_xp} XP за приглашение',
        icon='👥',
        link='/referrals',
    )


def notify_weekly_challenge(user_id: int, challenge_title: str, icon: str = '🏆') -> Notification:
    return create_notification(
        user_id, 'weekly_challenge',
        title=f'Челлендж выполнен: {challenge_title}',
        message='Отличная работа! Новый челлендж в понедельник.',
        icon=icon,
        link='/dashboard',
    )


def get_unread_count(user_id: int) -> int:
    return Notification.query.filter_by(user_id=user_id, read=False).count()
