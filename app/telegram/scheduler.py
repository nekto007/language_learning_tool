"""APScheduler jobs for Telegram notifications."""
import logging
import os
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from app.telegram.models import TelegramNotificationLog, TelegramUser
from app.telegram.notifications import (
    format_evening_summary,
    format_mission_morning_reminder,
    format_morning_reminder,
    format_nudge,
    format_streak_alert,
    format_streak_repair_alert,
    format_weekly_report,
    format_word_of_day,
)
from app.telegram.queries import (
    get_cards_url,
    get_current_streak,
    get_daily_plan_for_telegram,
    get_daily_summary,
    get_quickest_action,
    get_tomorrow_preview,
    get_weekly_report,
    has_activity_today,
)
from config.settings import DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_lock_conn = None

# Arbitrary 32-bit key identifying the "telegram scheduler" singleton in
# pg_advisory_lock space. Keep stable — changing it lets a second scheduler in.
_SCHEDULER_LOCK_KEY = 0x7E1E6004


def init_scheduler(app) -> None:
    """Initialize APScheduler within Flask app context.

    Holds a PostgreSQL session-level advisory lock so that EXACTLY ONE
    scheduler runs across the whole deployment. Every gunicorn worker AND
    every container (web + the dedicated `scheduler` container) imports
    run.py → create_app() → init_scheduler(), so without a cross-process lock
    each container would spawn its own _hourly_check and users get duplicate
    notifications. A file lock can't coordinate across containers (separate
    /tmp); a Postgres advisory lock can — only the connection that wins
    pg_try_advisory_lock starts the jobs. The lock is held for as long as
    `_lock_conn` stays open (process lifetime); if the process dies the
    connection drops and Postgres releases it so another process can take over.
    """
    global _scheduler, _lock_conn

    if not app.config.get('TELEGRAM_BOT_TOKEN'):
        logger.info('TELEGRAM_BOT_TOKEN not set — scheduler disabled')
        return

    if _scheduler is not None:
        return

    from sqlalchemy import text

    from app.utils.db import db
    conn = None
    try:
        # app_context is needed only to resolve db.engine (flask_sqlalchemy
        # reads current_app); the Connection and its advisory lock outlive it.
        #
        # AUTOCOMMIT is critical: without it SQLAlchemy 2.0 autobegins a
        # transaction on the first execute, leaving the held connection
        # idle-in-transaction. db_config sets idle_in_transaction_session_timeout
        # = 60s per connection, so Postgres would terminate the session after
        # a minute and RELEASE the session-level advisory lock — then a process
        # that starts >60s later (e.g. a staggered container) re-acquires the
        # freed lock and spins up a SECOND scheduler → duplicate notifications.
        # AUTOCOMMIT leaves no open transaction, so the connection stays plain-
        # idle and holds the lock for the whole process lifetime.
        with app.app_context():
            conn = db.engine.connect().execution_options(isolation_level='AUTOCOMMIT')
            got = conn.execute(
                text('SELECT pg_try_advisory_lock(:k)'),
                {'k': _SCHEDULER_LOCK_KEY},
            ).scalar()
    except Exception:
        logger.exception('Could not acquire scheduler advisory lock — skipping')
        # Close a connection opened before execute() raised, or it leaks
        # (advisory lock is best-effort; TelegramNotificationLog.claim is the
        # authoritative dedup) — audit E-089.
        if conn is not None:
            try:
                conn.close()
            except Exception:
                logger.warning('failed to close scheduler lock conn after error', exc_info=True)
        return

    if not got:
        conn.close()
        logger.info('Another process owns the scheduler — skipping (pid=%s)', os.getpid())
        return

    _lock_conn = conn  # keep open for the process lifetime to hold the lock

    _scheduler = BackgroundScheduler(timezone='UTC')
    _scheduler.add_job(
        _hourly_check,
        'interval',
        hours=1,
        args=[app],
        id='telegram_hourly',
        replace_existing=True,
    )
    # Channel publisher: publish_due runs every 5 minutes so a slot
    # scheduled at HH:MM fires within ~5 minutes of that time. The query is
    # cheap (status='queued' AND scheduled_for<=now) so the tighter cadence
    # is fine. queue_upcoming refills the next 7 days once daily.
    _scheduler.add_job(
        _channel_publish_due,
        'interval',
        minutes=5,
        args=[app],
        id='telegram_channel_publish',
        replace_existing=True,
    )
    _scheduler.add_job(
        _channel_refill_queue,
        'cron',
        hour=2,
        minute=0,
        args=[app],
        id='telegram_channel_queue_refill',
        replace_existing=True,
    )
    _scheduler.start()
    logger.info('Telegram scheduler started (pid=%s)', os.getpid())


def _channel_publish_due(app) -> None:
    """5-minute hook: deliver any queued channel posts that are now due.

    Always writes a watchdog timestamp (``telegram_channel_last_tick_iso``)
    even when nothing was sent, so the admin page can detect a stuck/missing
    scheduler — a stale timestamp means the APScheduler process is dead.
    """
    with app.app_context():
        try:
            from app.admin.site_settings import set_site_setting
            from app.telegram.channel_publisher import publish_due
            from app.utils.db import db as _db
            try:
                publish_due()
            finally:
                # Record liveness even if publish failed mid-flight.
                set_site_setting(
                    'telegram_channel_last_tick_iso',
                    datetime.now(timezone.utc).isoformat(timespec='seconds'),
                )
                _db.session.commit()
        except Exception:
            logger.exception('Channel publisher publish_due failed')


def _channel_refill_queue(app) -> None:
    """Daily hook: top up the next 7 days of morning + evening channel slots."""
    with app.app_context():
        try:
            from app.telegram.channel_publisher import queue_upcoming
            queue_upcoming(days_ahead=7)
        except Exception:
            logger.exception('Channel publisher queue_upcoming failed')


def _hourly_check(app) -> None:
    """Run every hour: send notifications to users whose local time matches."""
    with app.app_context():
        now_utc = datetime.now(timezone.utc)
        users = TelegramUser.query.filter_by(is_active=True).all()
        site_url = app.config.get('SITE_URL', '')

        for tg_user in users:
            try:
                tz = pytz.timezone(tg_user.timezone)
            except pytz.UnknownTimeZoneError:
                tz = pytz.timezone(DEFAULT_TIMEZONE)

            local_time = now_utc.astimezone(tz)
            local_hour = local_time.hour
            local_date = local_time.date()
            is_sunday = local_time.weekday() == 6

            try:
                _process_user(tg_user, local_hour, local_date, is_sunday, site_url)
                # Persist the send claims made in _process_user so concurrent
                # scheduler processes see them and can't re-send. Per-user commit
                # keeps the window small and isolates failures.
                from app.utils.db import db
                db.session.commit()
            except Exception:
                from app.utils.db import db
                db.session.rollback()
                logger.exception('Error processing user %s', tg_user.telegram_id)


def _process_user(tg_user: TelegramUser, local_hour: int, local_date,
                  is_sunday: bool, site_url: str) -> None:
    """Send appropriate notification based on user's local hour and preferences."""
    from app.auth.models import User
    from app.telegram.bot import send_message

    user_id = tg_user.user_id
    chat_id = tg_user.telegram_id

    def _guarded_send(kind: str, *args, **kwargs) -> None:
        """Send only if this (user, kind, local_date) hasn't been claimed yet.

        The claim is atomic against the UNIQUE constraint, so even if several
        scheduler processes hit this branch at once, exactly one sends.
        Claim-before-send means a failed send won't be retried today — for
        these reminders, no-duplicate is preferred over guaranteed re-delivery.
        """
        if TelegramNotificationLog.claim(user_id, kind, local_date):
            send_message(*args, **kwargs)

    user = User.query.get(user_id)
    name = user.username if user else 'друг'
    cards_url = get_cards_url(user_id, site_url) if site_url else ''
    user_tz = tg_user.timezone

    # Morning reminder (user's custom hour)
    if local_hour == tg_user.morning_hour and tg_user.morning_reminder:
        streak = get_current_streak(user_id, tz=user_tz)
        plan = get_daily_plan_for_telegram(user_id, tz=user_tz)
        if plan.get('mission'):
            text, reply_markup = format_mission_morning_reminder(
                name, streak, plan, site_url)
        else:
            text, reply_markup = format_morning_reminder(
                name, streak, plan, site_url, cards_url=cards_url)
        _guarded_send('tgn_morning', chat_id, text, reply_markup=reply_markup)

    # Word of the Day (1 hour after morning reminder). Independent `if` (not
    # `elif`) so a notification whose hour collides with another type isn't
    # silently dropped — each _guarded_send is claim-idempotent per kind/day
    # (audit E-090). morning_hour is nullable=False default 9; use it directly
    # (the old `or 8` mistreated a valid 0 and disagreed with the line above).
    _morning_hour = tg_user.morning_hour if tg_user.morning_hour is not None else 9
    if local_hour == _morning_hour + 1 and tg_user.morning_reminder:
        from app.study.word_of_day import get_word_of_day
        word_data = get_word_of_day(user_id)
        if word_data:
            text, keyboard = format_word_of_day(word_data, site_url)
            if text:
                _guarded_send('tgn_wotd', chat_id, text, reply_markup=keyboard)

    # Nudge (user's custom hour, only if no activity today and has a quick action)
    if local_hour == tg_user.nudge_hour and tg_user.nudge_enabled:
        if not has_activity_today(user_id, tz=user_tz):
            quick_action = get_quickest_action(user_id, tz=user_tz)
            if quick_action:
                text = format_nudge(name, site_url,
                                    quick_action=quick_action,
                                    cards_url=cards_url)
                _guarded_send('tgn_nudge', chat_id, text)

    # Sunday weekly report (1 hour before evening summary)
    if local_hour == max(tg_user.evening_hour - 1, 0) and is_sunday and tg_user.evening_summary:
        report = get_weekly_report(user_id, tz=user_tz)
        text = format_weekly_report(report, site_url)
        _guarded_send('tgn_weekly', chat_id, text)

    # Evening summary (user's custom hour, only if there was activity)
    if local_hour == tg_user.evening_hour and tg_user.evening_summary:
        if has_activity_today(user_id, tz=user_tz):
            summary = get_daily_summary(user_id, tz=user_tz)
            streak = get_current_streak(user_id, tz=user_tz)
            tomorrow = get_tomorrow_preview(user_id)
            text, reply_markup = format_evening_summary(
                name, summary, streak, site_url, tomorrow=tomorrow,
                user_id=user_id,
            )
            _guarded_send('tgn_evening', chat_id, text, reply_markup=reply_markup)

    # Streak alert (user's custom hour, only if no activity and streak > 0)
    if local_hour == tg_user.streak_hour and tg_user.streak_alert:
        if not has_activity_today(user_id, tz=user_tz):
            streak = get_current_streak(user_id, tz=user_tz)
            if streak > 0:
                quick_action = get_quickest_action(user_id, tz=user_tz)
                text = format_streak_alert(name, streak, site_url,
                                           quick_action=quick_action,
                                           cards_url=cards_url)
                _guarded_send('tgn_streak', chat_id, text)
            else:
                # Streak is 0 — check if there's a repairable missed date
                from app.achievements.streak_service import (
                    find_missed_date,
                    get_or_create_coins,
                    get_repair_cost,
                )
                missed = find_missed_date(user_id, tz=user_tz)
                if missed:
                    cost = get_repair_cost(user_id)
                    coins = get_or_create_coins(user_id)
                    # Estimate what streak was before the break
                    prev_streak = get_current_streak(user_id, tz=user_tz)
                    # Walk back from missed date to count streak before break
                    from datetime import datetime, timedelta
                    from datetime import timezone as tz_mod

                    from app.achievements.models import StreakEvent
                    from app.telegram.queries import _has_activity_in_range, _user_day_boundaries
                    old_streak = 0
                    missed_offset = (datetime.now(tz_mod.utc).date() - missed).days
                    for offset in range(missed_offset + 1, 366):
                        day_start, day_end = _user_day_boundaries(user_tz, offset_days=-offset)
                        check_date = (datetime.now(tz_mod.utc) - timedelta(days=offset)).date()
                        if _has_activity_in_range(user_id, day_start, day_end):
                            old_streak += 1
                        else:
                            repaired = StreakEvent.query.filter(
                                StreakEvent.user_id == user_id,
                                StreakEvent.event_date == check_date,
                                StreakEvent.event_type.in_(['free_repair', 'spent_repair']),
                            ).first()
                            if repaired:
                                old_streak += 1
                            else:
                                break
                    if old_streak > 0:
                        text, reply_markup = format_streak_repair_alert(
                            name, old_streak, cost, coins.balance, site_url,
                        )
                        _guarded_send('tgn_repair', chat_id, text, reply_markup=reply_markup)
