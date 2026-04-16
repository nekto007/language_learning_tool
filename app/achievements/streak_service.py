"""Streak recovery service — coin earning, free/paid repair, progressive requirements."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from app.utils.db import db
from app.achievements.models import StreakCoins, StreakEvent
from app.daily_plan.models import MODE_CATEGORY_MAP
from config.settings import DEFAULT_TIMEZONE

logger = logging.getLogger(__name__)


def get_required_steps(streak_length: int, steps_total: int) -> int:
    """Return minimum steps needed to maintain streak at given length.

    Progressive tiers:
      1-14 days:  1 step
      15-29 days: 2 steps
      30-59 days: 3 steps
      60+ days:   all steps
    """
    if streak_length >= 60:
        required = steps_total
    elif streak_length >= 30:
        required = 3
    elif streak_length >= 15:
        required = 2
    else:
        required = 1
    return min(required, steps_total)


_MODE_DONE_CHECK = MODE_CATEGORY_MAP


def _compute_phase_completion(phases: list[dict], daily_summary: dict) -> dict[str, bool]:
    """Infer phase completion from daily_summary activity data."""
    checks = {
        'words': (daily_summary.get('words_reviewed', 0) > 0
                  or daily_summary.get('srs_words_reviewed', 0) > 0),
        'lesson': daily_summary.get('lessons_count', 0) > 0,
        'grammar': daily_summary.get('grammar_exercises', 0) > 0,
        'books': len(daily_summary.get('books_read', [])) > 0,
        'book_course': daily_summary.get('book_course_lessons_today', 0) > 0,
    }

    result: dict[str, bool] = {}
    deferred: list[dict] = []
    for p in phases:
        mode = p.get('mode', '')
        category = _MODE_DONE_CHECK.get(mode)
        if category:
            result[p['id']] = checks.get(category, False)
        elif mode == 'success_marker':
            deferred.append(p)
        else:
            result[p['id']] = p.get('completed', False)
    for p in deferred:
        result[p['id']] = all(
            result.get(q['id'], False)
            for q in phases
            if q.get('required', True) and q['id'] != p['id']
        )
    return result


def compute_plan_steps(daily_plan: dict, daily_summary: dict) -> tuple[dict, dict, int, int]:
    """Compute plan completion and step counts from plan + summary data.

    Returns (plan_completion, steps_available, steps_done, steps_total).
    Single source of truth — used by dashboard route, API, and bot.

    Supports mission phases format, new step-state format, and legacy flat format.
    """
    phases = daily_plan.get('phases')
    if phases:
        plan_completion = _compute_phase_completion(phases, daily_summary)
        steps_available = {p['id']: True for p in phases}

        required_phases = [p for p in phases if p.get('required', True)]
        steps_done = sum(1 for p in required_phases if plan_completion.get(p['id'], False))
        steps_total = len(required_phases)
        return plan_completion, steps_available, steps_done, steps_total

    steps = daily_plan.get('steps')

    if steps:
        # ── New per-step state machine format ──
        DONE_STATES = {'completed', 'all_reviewed', 'all_done'}
        # A step is "available" if it exists (not None)
        # A step is "done" if its state is in DONE_STATES

        plan_completion = {}
        steps_available = {}

        for key in ('lesson', 'grammar', 'words', 'books', 'book_course_practice'):
            step = steps.get(key)
            if step is not None:
                steps_available[key] = True
                plan_completion[key] = step.get('state') in DONE_STATES
            else:
                plan_completion[key] = False

        steps_done = sum(1 for k in steps_available if plan_completion.get(k, False))
        steps_total = len(steps_available)

        return plan_completion, steps_available, steps_done, steps_total

    # ── Legacy flat format (for API/bot backward compat) ──
    bc_lesson = daily_plan.get('book_course_lesson')
    bc_done = daily_plan.get('book_course_done_today', False)
    bc_is_reading = bc_lesson and bc_lesson.get('lesson_type') == 'reading'

    plan_completion = {
        'lesson': daily_summary['lessons_count'] > 0,
        'grammar': daily_summary['grammar_exercises'] > 0,
        'words': (daily_summary.get('words_reviewed', 0) > 0
                  or daily_summary.get('srs_words_reviewed', 0) > 0),
        'books': bc_done if bc_is_reading else len(daily_summary.get('books_read', [])) > 0,
        'book_course_practice': bc_done if (bc_lesson and not bc_is_reading) else False,
    }

    # Auto-complete words if user has words but none are due
    if daily_plan.get('has_any_words') and not daily_plan.get('words_due'):
        plan_completion['words'] = True

    # Step is "available" if it has pending work OR was already completed today
    steps_available = {k: v for k, v in {
        'lesson': daily_plan.get('next_lesson') or plan_completion.get('lesson'),
        'grammar': daily_plan.get('grammar_topic') or plan_completion.get('grammar'),
        'words': daily_plan.get('words_due') or plan_completion.get('words'),
        'books': daily_plan.get('book_to_read') or (bc_lesson if bc_is_reading else None) or plan_completion.get('books'),
        'book_course_practice': (bc_lesson if (bc_lesson and not bc_is_reading) else None) or plan_completion.get('book_course_practice'),
    }.items() if v}

    steps_done = sum(1 for k in steps_available if plan_completion.get(k))
    steps_total = len(steps_available)

    return plan_completion, steps_available, steps_done, steps_total


def process_streak_on_activity(user_id: int, steps_done: int, steps_total: int,
                               tz: str = DEFAULT_TIMEZONE) -> dict:
    """Process streak: save completion, award coin, attempt free repair.

    Call this from any entry point (dashboard, API, bot).
    Returns dict with streak info and whether repair happened.
    """
    import pytz
    from app.telegram.queries import get_current_streak, has_activity_today

    # Compute the user's local "today" so that earned_daily rows are keyed
    # to the correct date regardless of the server's timezone.
    try:
        tz_obj = pytz.timezone(tz)
    except pytz.UnknownTimeZoneError:
        tz_obj = pytz.timezone(DEFAULT_TIMEZONE)
    user_today = datetime.now(tz_obj).date()

    # Only award coins and record completion when the user has genuine
    # activity in one of the authoritative tables (lessons, grammar,
    # words, books, book-courses).  steps_done can be positive from
    # auto-completed plan steps (e.g. words 'all_reviewed' when nothing
    # is due), which should not count as real study.
    real_activity = has_activity_today(user_id, tz=tz)

    if steps_done > 0 and real_activity:
        earn_daily_coin(user_id, for_date=user_today,
                        steps_done=steps_done, steps_total=steps_total)
        save_daily_completion(user_id, steps_done, steps_total,
                              for_date=user_today)

    streak_status = get_streak_status(user_id, tz=tz, steps_total=max(steps_total, 1))
    required_steps = streak_status.get('required_steps', 1)
    streak_repaired = False

    # Attempt free repair if enough steps done AND user has real activity
    if steps_total > 0 and steps_done >= required_steps and real_activity:
        missed = find_missed_date(user_id, tz=tz)
        if missed:
            apply_free_repair(user_id, missed, steps_done, steps_total)
            db.session.commit()
            streak = get_current_streak(user_id, tz=tz)
            streak_status = get_streak_status(user_id, tz=tz, steps_total=max(steps_total, 1))
            streak_status['streak'] = streak
            required_steps = streak_status.get('required_steps', 1)
            streak_repaired = True

    # Check streak milestones and award bonus coins
    milestone_reward = check_streak_milestone(
        user_id, streak_status.get('streak', 0), for_date=user_today)

    db.session.commit()

    return {
        'streak_status': streak_status,
        'required_steps': required_steps,
        'streak_repaired': streak_repaired,
        'steps_done': steps_done,
        'steps_total': steps_total,
        'milestone_reward': milestone_reward,
    }


STREAK_MILESTONES = {
    7: 5,
    14: 10,
    30: 20,
    60: 50,
    100: 100,
}


def check_streak_milestone(user_id: int, current_streak: int,
                           for_date: date | None = None) -> dict | None:
    """Check if current streak hits a milestone and award bonus coins.

    Returns milestone info dict if awarded, None otherwise.
    """
    if current_streak not in STREAK_MILESTONES:
        return None

    reward = STREAK_MILESTONES[current_streak]

    # Check if already awarded for this milestone
    already = StreakEvent.query.filter_by(
        user_id=user_id,
        event_type='milestone',
    ).filter(
        StreakEvent.details.contains({'streak': current_streak})
        if hasattr(StreakEvent.details, 'contains')
        else StreakEvent.event_type == 'milestone'  # fallback
    ).first()

    if already and already.details and already.details.get('streak') == current_streak:
        return None

    today = for_date or date.today()
    coins = get_or_create_coins(user_id)
    coins.earn(reward)
    db.session.add(StreakEvent(
        user_id=user_id,
        event_type='milestone',
        coins_delta=reward,
        event_date=today,
        details={'streak': current_streak, 'reward': reward},
    ))

    # Send notification
    try:
        from app.notifications.services import notify_streak_milestone
        notify_streak_milestone(user_id, current_streak, reward)
    except Exception:
        logger.warning("Failed to send streak milestone notification for user %s, streak %s",
                        user_id, current_streak, exc_info=True)

    return {'streak': current_streak, 'reward': reward}


def get_milestone_history(user_id: int) -> list[dict]:
    """Get all streak milestones earned by user."""
    events = StreakEvent.query.filter_by(
        user_id=user_id,
        event_type='milestone',
    ).order_by(StreakEvent.event_date.desc()).all()

    return [
        {
            'streak': (e.details or {}).get('streak', 0),
            'reward': (e.details or {}).get('reward', 0),
            'date': e.event_date,
        }
        for e in events
    ]


def get_streak_calendar(user_id: int, days: int = 90, tz: str = DEFAULT_TIMEZONE) -> dict:
    """Get streak calendar data for the last N days.

    Uses a single batched UNION query to find all active dates (same 5
    activity sources as the per-day streak checker), then merges with
    StreakEvent dates.  Replaces the previous per-day loop that could
    generate hundreds of queries.

    Returns dict with:
      - active_dates: list of date strings (YYYY-MM-DD) where user was active
      - total_active_days: total count
      - longest_streak: longest consecutive run
      - current_streak: current consecutive run
    """
    import pytz
    from sqlalchemy import Date, cast, func

    from app.curriculum.models import LessonProgress
    from app.grammar_lab.models import UserGrammarExercise
    from app.study.models import UserCardDirection, UserWord
    from app.books.models import UserChapterProgress
    from app.curriculum.daily_lessons import UserLessonProgress

    try:
        tz_obj = pytz.timezone(tz)
    except pytz.UnknownTimeZoneError:
        tz_obj = pytz.timezone(DEFAULT_TIMEZONE)
    tz = tz_obj.zone

    local_today = datetime.now(tz_obj).date()
    from_date = local_today - timedelta(days=days)
    start_utc = datetime.now(timezone.utc) - timedelta(days=days + 1)

    # --- StreakEvent dates (earned_daily + repairs) ---
    event_dates: set[date] = set()
    for ev in StreakEvent.query.filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type.in_(['earned_daily', 'free_repair', 'spent_repair']),
        StreakEvent.event_date >= from_date,
    ):
        event_dates.add(ev.event_date)

    def _local_date(col):
        return cast(func.timezone(tz, func.timezone('UTC', col)), Date)

    q1 = (
        db.session.query(_local_date(LessonProgress.last_activity).label('d'))
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.last_activity >= start_utc,
            LessonProgress.last_activity.isnot(None),
        )
    )
    q2 = (
        db.session.query(_local_date(UserGrammarExercise.last_reviewed).label('d'))
        .filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.last_reviewed >= start_utc,
            UserGrammarExercise.last_reviewed.isnot(None),
        )
    )
    q3 = (
        db.session.query(_local_date(UserCardDirection.last_reviewed).label('d'))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.last_reviewed >= start_utc,
            UserCardDirection.last_reviewed.isnot(None),
        )
    )
    q4 = (
        db.session.query(_local_date(UserChapterProgress.updated_at).label('d'))
        .filter(
            UserChapterProgress.user_id == user_id,
            UserChapterProgress.updated_at >= start_utc,
            UserChapterProgress.updated_at.isnot(None),
        )
    )
    q5 = (
        db.session.query(_local_date(UserLessonProgress.completed_at).label('d'))
        .filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.completed_at >= start_utc,
            UserLessonProgress.completed_at.isnot(None),
        )
    )

    try:
        union = q1.union(q2, q3, q4, q5).subquery()
        activity_rows = db.session.query(union.c.d).distinct().all()
        activity_dates: set[date] = {row[0] for row in activity_rows if row[0] is not None}
    except Exception:
        logger.exception("Failed to check activity for streak calendar user %s", user_id)
        activity_dates = set()

    # Merge activity dates with streak events, clamp to window
    all_active = (activity_dates | event_dates) & {
        local_today - timedelta(days=i) for i in range(days)
    }

    active_dates_str = sorted(d.isoformat() for d in all_active)

    # Calculate longest streak and current streak from all_active
    sorted_dates = sorted(all_active)
    longest = 0
    current = 0
    prev = None
    for d in sorted_dates:
        if prev and (d - prev).days == 1:
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        prev = d

    # Compute current streak by walking backward from today through all_active.
    # This reuses the batched calendar data instead of issuing per-day queries.
    curr_streak = 0
    for offset in range(days):
        check_date = local_today - timedelta(days=offset)
        if check_date in all_active:
            curr_streak += 1
        elif offset == 0:
            # No activity today — streak may still be alive (today isn't over)
            continue
        else:
            break

    # If the streak reaches the edge of the calendar window, it may extend
    # further back. Fall back to the authoritative day-by-day walk only then.
    if curr_streak >= days - 1:
        from app.telegram.queries import get_current_streak
        curr_streak = get_current_streak(user_id, tz=tz)

    return {
        'active_dates': active_dates_str,
        'total_active_days': len(all_active),
        'longest_streak': max(longest, curr_streak),
        'current_streak': curr_streak,
    }


def get_or_create_coins(user_id: int) -> StreakCoins:
    """Get or create StreakCoins record for user."""
    coins = StreakCoins.query.filter_by(user_id=user_id).first()
    if not coins:
        coins = StreakCoins(user_id=user_id)
        db.session.add(coins)
        db.session.flush()
    return coins


def save_daily_completion(user_id: int, steps_done: int, steps_total: int,
                          for_date: date | None = None) -> None:
    """Save/update steps_done and steps_total on today's earned_daily event.

    If no earned_daily event exists yet, creates one (without coin award —
    coin is awarded separately via earn_daily_coin).
    """
    today = for_date or date.today()
    event = StreakEvent.query.filter_by(
        user_id=user_id, event_type='earned_daily', event_date=today
    ).first()
    if event:
        event.steps_done = steps_done
        event.steps_total = steps_total
    else:
        db.session.add(StreakEvent(
            user_id=user_id, event_type='earned_daily',
            coins_delta=0, event_date=today,
            steps_done=steps_done, steps_total=steps_total,
        ))


def earn_daily_coin(user_id: int, for_date: date | None = None,
                    steps_done: int | None = None,
                    steps_total: int | None = None) -> bool:
    """Award 1 streak coin for daily activity. Returns True if awarded.

    Uses FOR UPDATE on the StreakCoins row to serialize concurrent
    requests for the same user, preventing duplicate earned_daily rows.
    """
    today = for_date or date.today()

    # Lock user's coin row first to serialize concurrent attempts
    coins = StreakCoins.query.filter_by(user_id=user_id).with_for_update().first()
    if not coins:
        try:
            with db.session.begin_nested():
                coins = StreakCoins(user_id=user_id)
                db.session.add(coins)
                db.session.flush()
        except IntegrityError:
            # Concurrent request already created the row — the context
            # manager rolled back the savepoint, leaving the outer
            # transaction intact.
            coins = StreakCoins.query.filter_by(user_id=user_id).with_for_update().first()

    if coins is None:
        coins = get_or_create_coins(user_id)

    already = StreakEvent.query.filter_by(
        user_id=user_id, event_type='earned_daily', event_date=today
    ).first()
    if already:
        # Update steps if provided
        if steps_done is not None:
            already.steps_done = steps_done
        if steps_total is not None:
            already.steps_total = steps_total
        return False

    coins.earn(1)
    db.session.add(StreakEvent(
        user_id=user_id, event_type='earned_daily',
        coins_delta=1, event_date=today,
        steps_done=steps_done, steps_total=steps_total,
    ))
    return True


def has_repair_for_date(user_id: int, target_date: date) -> bool:
    """Check if a repair (free or paid) exists for a specific date."""
    return StreakEvent.query.filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_date == target_date,
        StreakEvent.event_type.in_(['free_repair', 'spent_repair']),
    ).first() is not None


def get_repair_cost(user_id: int) -> int:
    """Sliding repair cost: 1st/month=3, 2nd=5, 3rd+=10."""
    month_start = date.today().replace(day=1)
    repairs_count = StreakEvent.query.filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == 'spent_repair',
        StreakEvent.event_date >= month_start,
    ).count()
    if repairs_count == 0:
        return 3
    elif repairs_count == 1:
        return 5
    return 10


def apply_free_repair(user_id: int, missed_date: date,
                      steps_done: int | None = None,
                      steps_total: int | None = None) -> bool:
    """Apply free repair for a missed date. Returns True on success."""
    if has_repair_for_date(user_id, missed_date):
        return False

    details: dict = {'reason': 'progressive_plan_complete'}
    if steps_done is not None:
        details['steps_done'] = steps_done
        details['steps_total'] = steps_total

    db.session.add(StreakEvent(
        user_id=user_id, event_type='free_repair',
        coins_delta=0, event_date=missed_date,
        details=details,
    ))
    return True


def apply_paid_repair(user_id: int, missed_date: date) -> dict:
    """Apply paid repair. Returns result dict."""
    if has_repair_for_date(user_id, missed_date):
        return {'success': False, 'cost': 0, 'balance': 0, 'error': 'already_repaired'}

    if (date.today() - missed_date).days > 2:
        return {'success': False, 'cost': 0, 'balance': 0, 'error': 'expired'}

    cost = get_repair_cost(user_id)
    coins = get_or_create_coins(user_id)

    if not coins.spend(cost):
        return {'success': False, 'cost': cost, 'balance': coins.balance, 'error': 'insufficient_coins'}

    db.session.add(StreakEvent(
        user_id=user_id, event_type='spent_repair',
        coins_delta=-cost, event_date=missed_date,
        details={'cost': cost},
    ))
    return {'success': True, 'cost': cost, 'balance': coins.balance, 'error': None}


def find_missed_date(user_id: int, tz: str = DEFAULT_TIMEZONE,
                     max_days: int = 7) -> date | None:
    """Find the most recent missed date that could be repaired.

    Walks backwards up to max_days looking for the first gap in activity
    that hasn't been repaired yet. Stops at the first day WITH activity
    (the gap must be adjacent to the current streak).
    """
    from app.telegram.queries import _user_day_boundaries, _has_activity_in_range
    import pytz

    local_now = datetime.now(pytz.timezone(tz))

    for offset in range(1, max_days + 1):
        day_start, day_end = _user_day_boundaries(tz, offset_days=-offset)
        check_date = local_now.date() - timedelta(days=offset)

        if _has_activity_in_range(user_id, day_start, day_end):
            # Activity found — any gap must be BEFORE this day
            continue
        elif has_repair_for_date(user_id, check_date):
            # Already repaired — keep looking further back
            continue
        else:
            # Found an unrepaired gap — return it
            return check_date
    return None


def get_streak_status(user_id: int, tz: str = DEFAULT_TIMEZONE,
                      steps_total: int = 4) -> dict:
    """Get full streak status for dashboard display."""
    from app.telegram.queries import get_current_streak, has_activity_today

    streak = get_current_streak(user_id, tz=tz)
    coins = get_or_create_coins(user_id)
    missed = find_missed_date(user_id, tz=tz)
    required = get_required_steps(streak, steps_total)

    return {
        'streak': streak,
        'coins_balance': coins.balance,
        'has_activity_today': has_activity_today(user_id, tz=tz),
        'can_repair': missed is not None,
        'missed_date': missed.isoformat() if missed else None,
        'repair_cost': get_repair_cost(user_id) if missed else None,
        'required_steps': required,
        'steps_total': steps_total,
    }
