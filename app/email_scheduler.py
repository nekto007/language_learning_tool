"""Email scheduler for automated re-engagement emails.

Runs daily via APScheduler. Sends emails to inactive users:
- Day 3: personalized content reminder
- Day 7: progress summary + streak warning
- Day 30: new features since they left
"""
import logging
import secrets
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.auth.models import User
from app.utils.db import db
from app.utils.email_utils import email_sender

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# Unsubscribe token field name on User model
UNSUBSCRIBE_TOKEN_FIELD = 'email_unsubscribe_token'


def get_inactive_users(days_inactive: int, tolerance_hours: int = 12) -> list[User]:
    """Find users inactive for exactly `days_inactive` days (within tolerance)."""
    now = datetime.now(timezone.utc)
    target = now - timedelta(days=days_inactive)
    window_start = target - timedelta(hours=tolerance_hours)
    window_end = target + timedelta(hours=tolerance_hours)

    return User.query.filter(
        User.active == True,
        User.email_opted_out == False,
        User.last_login.isnot(None),
        User.last_login.between(window_start, window_end),
        User.email.isnot(None),
    ).all()


def ensure_unsubscribe_token(user: User) -> str:
    """Generate unsubscribe token if not set. Skip if user opted out."""
    if getattr(user, 'email_opted_out', False):
        return ''
    token = getattr(user, UNSUBSCRIBE_TOKEN_FIELD, None)
    if not token:
        token = secrets.token_urlsafe(32)
        setattr(user, UNSUBSCRIBE_TOKEN_FIELD, token)
        db.session.commit()
    return token


def send_day3_email(user: User) -> bool:
    """Send Day 3 inactive email with personalized content."""
    context = {
        'username': user.username,
        'site_url': 'https://llt-english.com',
        'unsubscribe_url': f'https://llt-english.com/unsubscribe?token={ensure_unsubscribe_token(user)}',
    }
    return email_sender.send_email(
        subject=f'{user.username}, мы скучаем! Продолжи изучение английского',
        to_email=user.email,
        template_name='reengagement/day3',
        context=context,
    )


def send_day7_email(user: User) -> bool:
    """Send Day 7 inactive email with progress summary."""
    from app.curriculum.models import LessonProgress
    from sqlalchemy import func

    completed = LessonProgress.query.filter_by(
        user_id=user.id, status='completed'
    ).count()

    context = {
        'username': user.username,
        'lessons_completed': completed,
        'site_url': 'https://llt-english.com',
        'unsubscribe_url': f'https://llt-english.com/unsubscribe?token={ensure_unsubscribe_token(user)}',
    }
    return email_sender.send_email(
        subject=f'{user.username}, не теряй прогресс — уже {completed} уроков!',
        to_email=user.email,
        template_name='reengagement/day7',
        context=context,
    )


def send_day30_email(user: User) -> bool:
    """Send Day 30 inactive email with new features."""
    context = {
        'username': user.username,
        'site_url': 'https://llt-english.com',
        'unsubscribe_url': f'https://llt-english.com/unsubscribe?token={ensure_unsubscribe_token(user)}',
    }
    return email_sender.send_email(
        subject=f'{user.username}, у нас новые функции! Возвращайся',
        to_email=user.email,
        template_name='reengagement/day30',
        context=context,
    )


def run_reengagement_job() -> None:
    """Main job: check for inactive users and send appropriate emails."""
    from flask import current_app
    logger.info('Running re-engagement email job')

    sent = 0
    for user in get_inactive_users(3):
        if send_day3_email(user):
            sent += 1

    for user in get_inactive_users(7):
        if send_day7_email(user):
            sent += 1

    for user in get_inactive_users(30):
        if send_day30_email(user):
            sent += 1

    logger.info(f'Re-engagement emails sent: {sent}')


def init_email_scheduler(app) -> None:
    """Initialize email scheduler within Flask app context."""
    global _scheduler

    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()

    def job_wrapper():
        with app.app_context():
            try:
                run_reengagement_job()
            except Exception as e:
                logger.error(f'Re-engagement job failed: {e}')

    # Run daily at 10:00 UTC
    _scheduler.add_job(
        job_wrapper,
        'cron',
        hour=10,
        minute=0,
        id='reengagement_emails',
        replace_existing=True,
    )

    _scheduler.start()
    logger.info('Email scheduler started')
