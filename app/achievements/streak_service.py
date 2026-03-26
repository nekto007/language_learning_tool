"""Streak recovery service — coin earning, free/paid repair."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.utils.db import db
from app.achievements.models import StreakCoins, StreakEvent


def get_or_create_coins(user_id: int) -> StreakCoins:
    """Get or create StreakCoins record for user."""
    coins = StreakCoins.query.filter_by(user_id=user_id).first()
    if not coins:
        coins = StreakCoins(user_id=user_id)
        db.session.add(coins)
        db.session.flush()
    return coins


def earn_daily_coin(user_id: int, for_date: date | None = None) -> bool:
    """Award 1 streak coin for daily activity. Returns True if awarded."""
    today = for_date or date.today()
    already = StreakEvent.query.filter_by(
        user_id=user_id, event_type='earned_daily', event_date=today
    ).first()
    if already:
        return False

    coins = get_or_create_coins(user_id)
    coins.earn(1)
    db.session.add(StreakEvent(
        user_id=user_id, event_type='earned_daily',
        coins_delta=1, event_date=today,
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


def apply_free_repair(user_id: int, missed_date: date) -> bool:
    """Apply free repair for a missed date. Returns True on success."""
    if has_repair_for_date(user_id, missed_date):
        return False

    db.session.add(StreakEvent(
        user_id=user_id, event_type='free_repair',
        coins_delta=0, event_date=missed_date,
        details={'reason': 'daily_plan_100'},
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


def find_missed_date(user_id: int, tz: str = 'Europe/Moscow') -> date | None:
    """Find the most recent missed date within 48h that could be repaired."""
    from app.telegram.queries import _user_day_boundaries, _has_activity_in_range

    for offset in [1, 2]:
        day_start, day_end = _user_day_boundaries(tz, offset_days=-offset)
        if not _has_activity_in_range(user_id, day_start, day_end):
            missed = (datetime.now(timezone.utc) - timedelta(days=offset)).date()
            if not has_repair_for_date(user_id, missed):
                return missed
    return None


def get_streak_status(user_id: int, tz: str = 'Europe/Moscow') -> dict:
    """Get full streak status for dashboard display."""
    from app.telegram.queries import get_current_streak, has_activity_today

    streak = get_current_streak(user_id, tz=tz)
    coins = get_or_create_coins(user_id)
    missed = find_missed_date(user_id, tz=tz)

    return {
        'streak': streak,
        'coins_balance': coins.balance,
        'has_activity_today': has_activity_today(user_id, tz=tz),
        'can_repair': missed is not None,
        'missed_date': missed.isoformat() if missed else None,
        'repair_cost': get_repair_cost(user_id) if missed else None,
    }
