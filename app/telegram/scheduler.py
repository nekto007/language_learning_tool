"""APScheduler jobs for Telegram notifications."""
import fcntl
import logging
import os
import tempfile
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.background import BackgroundScheduler

from app.telegram.models import TelegramUser
from app.telegram.queries import (
    has_activity_today, get_current_streak,
    get_daily_summary, get_weekly_report,
    get_tomorrow_preview, get_quickest_action, get_cards_url,
    get_daily_plan_for_telegram,
)
from app.telegram.notifications import (
    format_morning_reminder, format_evening_summary,
    format_nudge, format_streak_alert, format_streak_repair_alert,
    format_weekly_report, format_word_of_day,
    format_mission_morning_reminder,
)

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_lock_file = None


def init_scheduler(app) -> None:
    """Initialize APScheduler within Flask app context.

    Uses a file lock to ensure only one gunicorn worker starts the scheduler.
    """
    global _scheduler, _lock_file

    if not app.config.get('TELEGRAM_BOT_TOKEN'):
        logger.info('TELEGRAM_BOT_TOKEN not set — scheduler disabled')
        return

    if _scheduler is not None:
        return

    # Acquire exclusive lock — only one process wins
    lock_path = os.path.join(tempfile.gettempdir(), 'tg_scheduler.lock')
    _lock_file = open(lock_path, 'w')
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        logger.info('Another worker owns the scheduler — skipping')
        _lock_file.close()
        _lock_file = None
        return

    _scheduler = BackgroundScheduler(timezone='UTC')
    _scheduler.add_job(
        _hourly_check,
        'interval',
        hours=1,
        args=[app],
        id='telegram_hourly',
        replace_existing=True,
    )
    _scheduler.start()
    logger.info('Telegram scheduler started (pid=%s)', os.getpid())


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
                tz = pytz.timezone('Europe/Moscow')

            local_time = now_utc.astimezone(tz)
            local_hour = local_time.hour
            is_sunday = local_time.weekday() == 6

            try:
                _process_user(tg_user, local_hour, is_sunday, site_url)
            except Exception:
                logger.exception('Error processing user %s', tg_user.telegram_id)


def _process_user(tg_user: TelegramUser, local_hour: int,
                  is_sunday: bool, site_url: str) -> None:
    """Send appropriate notification based on user's local hour and preferences."""
    from app.telegram.bot import send_message
    from app.auth.models import User

    user_id = tg_user.user_id
    chat_id = tg_user.telegram_id

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
        send_message(chat_id, text, reply_markup=reply_markup)

    # Word of the Day (1 hour after morning reminder)
    elif local_hour == (tg_user.morning_hour or 8) + 1 and tg_user.morning_reminder:
        from app.study.word_of_day import get_word_of_day
        word_data = get_word_of_day(user_id)
        if word_data:
            text, keyboard = format_word_of_day(word_data, site_url)
            if text:
                send_message(chat_id, text, reply_markup=keyboard)

    # Nudge (user's custom hour, only if no activity today and has a quick action)
    elif local_hour == tg_user.nudge_hour and tg_user.nudge_enabled:
        if not has_activity_today(user_id, tz=user_tz):
            quick_action = get_quickest_action(user_id, tz=user_tz)
            if quick_action:
                text = format_nudge(name, site_url,
                                    quick_action=quick_action,
                                    cards_url=cards_url)
                send_message(chat_id, text)

    # Sunday weekly report (1 hour before evening summary)
    elif local_hour == max(tg_user.evening_hour - 1, 0) and is_sunday and tg_user.evening_summary:
        report = get_weekly_report(user_id, tz=user_tz)
        text = format_weekly_report(report, site_url)
        send_message(chat_id, text)

    # Evening summary (user's custom hour, only if there was activity)
    elif local_hour == tg_user.evening_hour and tg_user.evening_summary:
        if has_activity_today(user_id, tz=user_tz):
            summary = get_daily_summary(user_id, tz=user_tz)
            streak = get_current_streak(user_id, tz=user_tz)
            tomorrow = get_tomorrow_preview(user_id)
            text, reply_markup = format_evening_summary(
                name, summary, streak, site_url, tomorrow=tomorrow,
                user_id=user_id,
            )
            send_message(chat_id, text, reply_markup=reply_markup)

    # Streak alert (user's custom hour, only if no activity and streak > 0)
    elif local_hour == tg_user.streak_hour and tg_user.streak_alert:
        if not has_activity_today(user_id, tz=user_tz):
            streak = get_current_streak(user_id, tz=user_tz)
            if streak > 0:
                quick_action = get_quickest_action(user_id, tz=user_tz)
                text = format_streak_alert(name, streak, site_url,
                                           quick_action=quick_action,
                                           cards_url=cards_url)
                send_message(chat_id, text)
            else:
                # Streak is 0 — check if there's a repairable missed date
                from app.achievements.streak_service import (
                    find_missed_date, get_repair_cost, get_or_create_coins,
                )
                missed = find_missed_date(user_id, tz=user_tz)
                if missed:
                    cost = get_repair_cost(user_id)
                    coins = get_or_create_coins(user_id)
                    # Estimate what streak was before the break
                    prev_streak = get_current_streak(user_id, tz=user_tz)
                    # Walk back from missed date to count streak before break
                    from app.telegram.queries import _user_day_boundaries, _has_activity_in_range
                    from app.achievements.models import StreakEvent
                    from datetime import timedelta, datetime, timezone as tz_mod
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
                        send_message(chat_id, text, reply_markup=reply_markup)
