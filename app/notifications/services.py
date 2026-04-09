"""Notification creation service."""
from app.notifications.models import Notification
from app.utils.db import db


def create_notification(user_id: int, type: str, title: str,
                        message: str = '', link: str = '', icon: str = '🔔') -> Notification:
    """Create a notification for a user."""
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


def notify_level_up(user_id: int, new_level: int) -> Notification:
    return create_notification(
        user_id, 'level_up',
        title=f'Уровень {new_level}!',
        message='Поздравляем с новым уровнем!',
        icon='🎉',
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


def notify_referral(user_id: int, referred_username: str) -> Notification:
    return create_notification(
        user_id, 'referral',
        title=f'{referred_username} присоединился!',
        message='+100 XP за приглашение',
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
