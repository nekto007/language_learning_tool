"""Weekly challenge -- rotates every Monday, computed from existing data."""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.utils.db import db

logger = logging.getLogger(__name__)


def get_weekly_challenge(user_id: int) -> dict[str, Any]:
    """Return the current weekly challenge with progress for a user.

    The challenge type rotates based on ISO week number so that every Monday
    a new challenge appears automatically.  No new DB tables are required --
    progress is computed from existing models.
    """
    week_start = date.today() - timedelta(days=date.today().weekday())  # Monday
    week_num = date.today().isocalendar()[1]

    challenges = [
        {'type': 'words', 'target': 50, 'title': 'Выучи 50 новых слов', 'icon': '\U0001f4d6'},
        {'type': 'lessons', 'target': 5, 'title': 'Пройди 5 уроков', 'icon': '\U0001f3af'},
        {'type': 'grammar', 'target': 20, 'title': '20 грамматических упражнений', 'icon': '\U0001f9e0'},
        {'type': 'streak', 'target': 7, 'title': '7 дней подряд без пропусков', 'icon': '\U0001f525'},
    ]
    challenge = challenges[week_num % len(challenges)]

    current = _count_progress(user_id, challenge['type'], week_start)

    completed = current >= challenge['target']

    # Send notification on first completion this week
    if completed:
        _notify_challenge_completed(user_id, challenge, week_start)

    return {**challenge, 'current': current, 'completed': completed, 'week_start': week_start.isoformat()}


def _notify_challenge_completed(user_id: int, challenge: dict, week_start: date) -> None:
    """Send notification for weekly challenge completion (once per week)."""
    try:
        from app.notifications.models import Notification
        # Check if already notified this week
        week_start_utc = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc)
        already = Notification.query.filter(
            Notification.user_id == user_id,
            Notification.type == 'weekly_challenge',
            Notification.created_at >= week_start_utc,
        ).first()
        if already:
            return

        from app.notifications.services import create_notification
        create_notification(
            user_id, 'weekly_challenge',
            title=f'Челлендж выполнен: {challenge["title"]}',
            message='Отличная работа! Новый челлендж в понедельник.',
            icon=challenge.get('icon', '🏆'),
            link='/dashboard',
        )
        db.session.commit()
    except Exception:
        logger.exception("Failed to commit weekly challenge completion for user %s", user_id)


def get_weekly_digest(user_id: int) -> dict[str, Any]:
    """Return weekly progress digest data for the dashboard widget.

    Returns:
        days: list of 7 dicts (Mon-Sun) with keys: label, date, state
              (state: 'complete', 'partial', 'missed', 'future')
        week_xp: total XP earned this week
        prev_week_xp: total XP earned last week
        xp_diff: week_xp - prev_week_xp
        mission_counts: dict {progress: N, repair: N, reading: N}
    """
    from app.achievements.models import StreakEvent
    from app.achievements.xp_service import get_today_xp
    from sqlalchemy import Integer, func

    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = week_start - timedelta(days=1)

    # 7-day grid
    day_labels = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    days: list[dict[str, Any]] = []

    # Fetch all StreakEvents for this week once
    week_events = StreakEvent.query.filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_date >= week_start,
        StreakEvent.event_date <= today,
        StreakEvent.event_type.in_(['earned_daily', 'plan_completed', 'free_repair', 'spent_repair']),
    ).all()

    # Group by date
    events_by_date: dict[date, list[StreakEvent]] = {}
    for ev in week_events:
        events_by_date.setdefault(ev.event_date, []).append(ev)

    # Fetch plan_completed events for full completion indicator
    completed_dates: set[date] = {
        ev.event_date for ev in week_events
        if ev.event_type == 'plan_completed'
    }
    # earned_daily = at least partial activity
    active_dates: set[date] = {
        ev.event_date for ev in week_events
        if ev.event_type in ('earned_daily', 'free_repair')
    }

    for i in range(7):
        day_date = week_start + timedelta(days=i)
        if day_date > today:
            state = 'future'
        elif day_date in completed_dates:
            state = 'complete'
        elif day_date in active_dates:
            state = 'partial'
        else:
            state = 'missed'
        days.append({
            'label': day_labels[i],
            'date': day_date.isoformat(),
            'state': state,
            'is_today': day_date == today,
        })

    # Weekly XP sums
    def _sum_xp_for_range(start: date, end: date) -> int:
        result = (
            StreakEvent.query
            .filter(
                StreakEvent.user_id == user_id,
                StreakEvent.event_date >= start,
                StreakEvent.event_date <= end,
                StreakEvent.event_type.in_(['xp_phase', 'xp_perfect_day', 'xp_surprise']),
            )
            .with_entities(
                func.sum(StreakEvent.details['xp'].astext.cast(Integer))
            )
            .scalar()
        )
        return int(result or 0)

    week_xp = _sum_xp_for_range(week_start, today)
    prev_week_xp = _sum_xp_for_range(prev_week_start, prev_week_end)
    xp_diff = week_xp - prev_week_xp

    # Mission type distribution for this week
    mission_events = StreakEvent.query.filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_date >= week_start,
        StreakEvent.event_date <= today,
        StreakEvent.event_type == 'mission_selected',
    ).all()

    mission_counts: dict[str, int] = {'progress': 0, 'repair': 0, 'reading': 0}
    for ev in mission_events:
        if ev.details:
            mt = ev.details.get('mission_type', '')
            if mt in mission_counts:
                mission_counts[mt] += 1

    return {
        'days': days,
        'week_xp': week_xp,
        'prev_week_xp': prev_week_xp,
        'xp_diff': xp_diff,
        'mission_counts': mission_counts,
        'week_start': week_start.isoformat(),
    }


def _count_progress(user_id: int, challenge_type: str, week_start: date) -> int:
    """Count progress towards *challenge_type* since *week_start*."""
    from app.curriculum.models import LessonProgress
    from app.study.models import UserCardDirection, UserWord
    from app.grammar_lab.models import UserGrammarExercise
    from sqlalchemy import func

    week_start_utc = datetime(
        week_start.year, week_start.month, week_start.day,
        tzinfo=timezone.utc,
    )

    if challenge_type == 'words':
        return db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
            UserWord.user_id == user_id,
            UserCardDirection.first_reviewed >= week_start_utc,
            UserCardDirection.direction == 'eng-rus',
        ).scalar() or 0

    elif challenge_type == 'lessons':
        return LessonProgress.query.filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            LessonProgress.completed_at >= week_start_utc,
        ).count()

    elif challenge_type == 'grammar':
        return UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.last_reviewed >= week_start_utc,
        ).count()

    elif challenge_type == 'streak':
        from app.telegram.queries import get_current_streak
        return min(get_current_streak(user_id), 7)

    return 0
