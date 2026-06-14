"""Email scheduler for automated re-engagement emails.

Runs daily via APScheduler. Sends emails to inactive users:
- Day 3: personalized content reminder
- Day 7: progress summary + streak warning
- Day 30: new features since they left
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler

from app.auth.models import User
from app.utils.db import db
from app.utils.email_utils import email_sender

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

# Unsubscribe token field name on User model
UNSUBSCRIBE_TOKEN_FIELD = 'email_unsubscribe_token'

# Only deliver emails during this local-time window: [8, 20) — 8am inclusive, 8pm exclusive.
DELIVERY_HOUR_START = 8
DELIVERY_HOUR_END = 20


def is_delivery_window(user: User) -> bool:
    """Return True if user's local time is within the delivery window (8:00–19:59).

    Falls back to UTC if the timezone is unknown or invalid.
    """
    tz_name = getattr(user, 'timezone', None) or 'UTC'
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        tz = ZoneInfo('UTC')
    local_hour = datetime.now(tz).hour
    return DELIVERY_HOUR_START <= local_hour < DELIVERY_HOUR_END


def get_inactive_users(days_inactive: int, tolerance_hours: int = 12) -> list[User]:
    """Find users inactive for exactly `days_inactive` days (within tolerance)."""
    # Build bounds as NAIVE UTC to match the naive User.last_login column;
    # comparing aware bounds to a naive column drifts by the server session TZ
    # offset (audit E-086). End is exclusive so a user on the boundary isn't
    # selected on two consecutive runs (audit E-087).
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    target = now - timedelta(days=days_inactive)
    window_start = target - timedelta(hours=tolerance_hours)
    window_end = target + timedelta(hours=tolerance_hours)

    return User.query.filter(
        User.active == True,
        User.email_opted_out == False,
        User.notify_email_reminders == True,
        User.last_login.isnot(None),
        User.last_login >= window_start,
        User.last_login < window_end,
        User.email.isnot(None),
    ).all()


_REENGAGEMENT_EVENT_TYPE = 'reengagement_email'


def _claim_reengagement(user_id: int, campaign: str) -> bool:
    """Claim today's (user, campaign) re-engagement slot. True if newly claimed.

    Race-safe across processes via uq_streak_events_reengagement: the loser of
    a concurrent claim gets IntegrityError and returns False. Prevents the same
    campaign email from being sent twice in a day / across hourly runs
    (audit E-087). Caller commits.
    """
    from sqlalchemy.exc import IntegrityError

    from app.achievements.models import StreakEvent
    from app.utils.time_utils import get_user_local_date

    today = get_user_local_date(user_id)
    exists = StreakEvent.query.filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == _REENGAGEMENT_EVENT_TYPE,
        StreakEvent.event_date == today,
        StreakEvent.details['campaign'].astext == campaign,
    ).first()
    if exists is not None:
        return False
    try:
        with db.session.begin_nested():
            db.session.add(StreakEvent(
                user_id=user_id,
                event_type=_REENGAGEMENT_EVENT_TYPE,
                coins_delta=0,
                event_date=today,
                details={'campaign': campaign},
            ))
            db.session.flush()
    except IntegrityError:
        return False
    return True


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
    """Main job: check for inactive users and send appropriate emails.

    Runs hourly so every timezone's delivery window is reached (audit E-088).
    Each (user, campaign) is claimed before sending so the hourly cadence can't
    produce duplicates (audit E-087); the claim is committed per user.
    """
    logger.info('Running re-engagement email job')

    # Resolved at call time so the senders stay patchable in tests.
    campaigns = (
        (3, 'day3', send_day3_email),
        (7, 'day7', send_day7_email),
        (30, 'day30', send_day30_email),
    )

    sent = 0
    for days_inactive, campaign, sender in campaigns:
        for user in get_inactive_users(days_inactive):
            if not is_delivery_window(user):
                logger.debug('Skipping user %s: outside delivery window', user.id)
                continue
            if not _claim_reengagement(user.id, campaign):
                continue  # already sent this campaign today
            try:
                ok = sender(user)
            except Exception:
                logger.exception('re-engagement send failed user=%s campaign=%s', user.id, campaign)
                ok = False
            if ok:
                sent += 1
            db.session.commit()

    logger.info(f'Re-engagement emails sent: {sent}')


def run_lesson_progress_reconcile_job() -> None:
    """Safety-net sweep that flips stuck LessonProgress rows to 'completed'
    when the user already passed the lesson (per latest attempt or score).

    See ``app.curriculum.recovery`` for the trigger conditions. Idempotent;
    rows already 'completed' are not re-scanned.
    """
    from app.curriculum.recovery import reconcile_stuck_lesson_progress

    logger.info('Running lesson_progress reconcile job')
    report = reconcile_stuck_lesson_progress(db.session, dry_run=False)
    logger.info(
        'lesson_progress reconcile: scanned=%d flipped=%d (attempt=%d score=%d) errors=%d',
        report.scanned, report.flipped,
        report.flipped_by_attempt, report.flipped_by_score,
        len(report.errors),
    )


def init_email_scheduler(app, *, blocking: bool = False) -> None:
    """Initialize email scheduler within Flask app context.

    The scheduler runs in a daemon thread (``BackgroundScheduler``), so the
    calling process MUST stay alive for jobs to fire. When invoked via the
    ``flask start-email-scheduler`` CLI inside a container, Click returns
    immediately after this function — the daemon thread dies with the
    process and no job ever runs. Pass ``blocking=True`` from such entry
    points: this call then blocks on ``signal.pause()`` until the process
    receives a signal (SIGTERM from ``docker stop``), giving the scheduler
    thread an actual lifetime.
    """
    global _scheduler

    if _scheduler is not None:
        if blocking:
            _block_until_signal()
        return

    _scheduler = BackgroundScheduler()

    def job_wrapper():
        with app.app_context():
            try:
                run_reengagement_job()
            except Exception as e:
                logger.error(f'Re-engagement job failed: {e}')

    def reconcile_wrapper():
        with app.app_context():
            try:
                run_lesson_progress_reconcile_job()
            except Exception as e:
                logger.error(f'lesson_progress reconcile job failed: {e}')

    # Run hourly: a single daily 10:00-UTC fire never overlaps the local
    # 8-20 delivery window for far-east/west timezones, so those users would
    # never be emailed (audit E-088). Per-(user, campaign, day) claim keeps the
    # hourly cadence duplicate-free.
    _scheduler.add_job(
        job_wrapper,
        'cron',
        hour='*',
        minute=0,
        id='reengagement_emails',
        replace_existing=True,
    )

    # Daily safety-net sweep for stuck lesson_progress rows. 03:00 UTC sits
    # in low-traffic hours so a long backfill doesn't fight live writes.
    _scheduler.add_job(
        reconcile_wrapper,
        'cron',
        hour=3,
        minute=0,
        id='lesson_progress_reconcile',
        replace_existing=True,
    )

    _scheduler.start()
    logger.info('Email scheduler started')

    if blocking:
        _block_until_signal()


def _block_until_signal() -> None:
    """Block the calling thread until SIGTERM/SIGINT, keeping the daemon
    scheduler thread alive. ``signal.pause()`` is POSIX-only; on platforms
    without it we fall back to an infinite sleep loop.
    """
    import signal
    import time

    logger.info('Email scheduler blocking on signal; waiting for jobs')
    pause = getattr(signal, 'pause', None)
    if pause is not None:
        try:
            pause()
        except (KeyboardInterrupt, SystemExit):
            pass
        return
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass
