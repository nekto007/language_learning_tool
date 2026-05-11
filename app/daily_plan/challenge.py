"""Daily challenge service: one shared challenge per calendar day."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

from app.daily_plan.models import CHALLENGE_CATEGORIES

_BONUS_XP: dict[str, int] = {
    'speed_run': 50,
    'accuracy_focus': 60,
    'listening_deep': 40,
}

_LISTENING_TYPES = ('dictation', 'listening_immersion')


def _seed_today_challenge(challenge_date: date, db) -> 'DailyChallenge':
    """Create a deterministic daily challenge for challenge_date.

    Category rotates by date ordinal mod 3.
    listening_deep attaches the first available dictation/listening lesson.
    Caller must commit.
    """
    from app.daily_plan.models import DailyChallenge
    from app.curriculum.models import Lessons

    day_idx = challenge_date.toordinal() % len(CHALLENGE_CATEGORIES)
    category = CHALLENGE_CATEGORIES[day_idx]
    bonus_xp = _BONUS_XP[category]

    lesson_id: Optional[int] = None
    if category == 'listening_deep':
        lesson = (
            Lessons.query
            .filter(Lessons.type.in_(_LISTENING_TYPES))
            .order_by(Lessons.id)
            .first()
        )
        if lesson:
            lesson_id = lesson.id

    challenge = DailyChallenge(
        challenge_date=challenge_date,
        lesson_id=lesson_id,
        bonus_xp=bonus_xp,
        category=category,
    )
    db.session.add(challenge)
    db.session.flush()
    return challenge


def get_challenge_streak(user_id: int, db) -> int:
    """Return consecutive-day daily-challenge completion streak ending today or yesterday.

    Walks backward from today. If today has no completion the walk starts from
    yesterday (today's challenge may not be done yet). Mirrors the walk-backward
    logic used by get_listening_streak / get_writing_streak.
    """
    from app.daily_plan.models import DailyChallenge, DailyChallengeCompletion

    today = date.today()
    cutoff = today - timedelta(days=365)

    rows = (
        db.session.query(DailyChallenge.challenge_date)
        .join(DailyChallengeCompletion, DailyChallengeCompletion.challenge_id == DailyChallenge.id)
        .filter(
            DailyChallengeCompletion.user_id == user_id,
            DailyChallenge.challenge_date >= cutoff,
        )
        .distinct()
        .all()
    )
    active_dates = {row[0] for row in rows if row[0] is not None}

    streak = 0
    for offset in range(365):
        check_date = today - timedelta(days=offset)
        if check_date in active_dates:
            streak += 1
        elif offset == 0:
            continue  # No completion today — streak may still be alive via yesterday
        else:
            break

    return streak


def get_today_challenge(user_id: int, db) -> dict:
    """Return today's challenge dict with user completion status.

    Auto-seeds if no challenge exists for today. Safe to call multiple times.
    """
    from app.daily_plan.models import DailyChallenge, DailyChallengeCompletion

    today = date.today()
    challenge = DailyChallenge.query.filter_by(challenge_date=today).first()
    if challenge is None:
        challenge = _seed_today_challenge(today, db)
        db.session.commit()

    completion = DailyChallengeCompletion.query.filter_by(
        challenge_id=challenge.id,
        user_id=user_id,
    ).first()

    streak = get_challenge_streak(user_id, db)

    return {
        'id': challenge.id,
        'challenge_date': challenge.challenge_date.isoformat(),
        'lesson_id': challenge.lesson_id,
        'bonus_xp': challenge.bonus_xp,
        'category': challenge.category,
        'is_completed': completion is not None,
        'challenge_streak': streak,
        'completion': {
            'completed_at': completion.completed_at.isoformat(),
            'score': completion.score,
            'time_spent_seconds': completion.time_spent_seconds,
        } if completion else None,
    }


def complete_challenge(
    user_id: int,
    challenge_id: int,
    score: Optional[float],
    time_spent_seconds: Optional[int],
    db,
) -> dict:
    """Idempotently mark the daily challenge as completed for user.

    Returns a dict with completion details. No-op and returns already_completed=True
    if the user already completed this challenge.
    Caller must commit.
    """
    from app.daily_plan.models import DailyChallenge, DailyChallengeCompletion

    challenge = db.session.get(DailyChallenge, challenge_id)
    if challenge is None:
        raise ValueError(f'DailyChallenge id={challenge_id} not found')

    existing = DailyChallengeCompletion.query.filter_by(
        challenge_id=challenge_id,
        user_id=user_id,
    ).first()
    if existing:
        return {
            'challenge_id': challenge_id,
            'user_id': user_id,
            'already_completed': True,
            'completed_at': existing.completed_at.isoformat(),
        }

    completion = DailyChallengeCompletion(
        challenge_id=challenge_id,
        user_id=user_id,
        score=score,
        time_spent_seconds=time_spent_seconds,
    )
    db.session.add(completion)
    db.session.flush()

    try:
        from app.achievements.services import check_challenge_achievements
        check_challenge_achievements(user_id)
    except Exception:
        import logging
        logging.getLogger(__name__).exception(
            "Failed to check challenge achievements for user %s", user_id
        )

    return {
        'challenge_id': challenge_id,
        'user_id': user_id,
        'already_completed': False,
        'bonus_xp': challenge.bonus_xp,
        'completed_at': completion.completed_at.isoformat() if completion.completed_at else None,
    }


_SPEED_RUN_MAX_SECONDS = 300  # 5 minutes
_ACCURACY_FOCUS_MIN_SCORE = 90.0


def maybe_auto_complete_challenge(
    user_id: int,
    lesson_id: int,
    passed: bool,
    score: Optional[float],
    time_spent_seconds: Optional[int],
    db,
) -> Optional[dict]:
    """Auto-complete today's daily challenge if the lesson meets challenge criteria.

    Called from the lesson submission handler after a successful lesson result.
    - listening_deep: passed AND lesson_id matches challenge.lesson_id
    - accuracy_focus: passed AND score >= 90
    - speed_run: passed AND time_spent_seconds < 300 (client must provide)

    Returns the completion dict (with bonus_xp) when newly completed, or None.
    Caller must commit.
    """
    if not passed:
        return None

    from app.daily_plan.models import DailyChallenge, DailyChallengeCompletion

    today = date.today()
    challenge = DailyChallenge.query.filter_by(challenge_date=today).first()
    if challenge is None:
        return None

    existing = DailyChallengeCompletion.query.filter_by(
        challenge_id=challenge.id,
        user_id=user_id,
    ).first()
    if existing:
        return None

    qualifies = False
    if challenge.category == 'listening_deep' and challenge.lesson_id == lesson_id:
        qualifies = True
    elif challenge.category == 'accuracy_focus' and score is not None and score >= _ACCURACY_FOCUS_MIN_SCORE:
        qualifies = True
    elif challenge.category == 'speed_run' and time_spent_seconds is not None and time_spent_seconds < _SPEED_RUN_MAX_SECONDS:
        qualifies = True

    if not qualifies:
        return None

    try:
        result = complete_challenge(
            user_id=user_id,
            challenge_id=challenge.id,
            score=score,
            time_spent_seconds=time_spent_seconds,
            db=db,
        )
        from app.achievements.xp_service import award_xp
        bonus_xp = result.get('bonus_xp', 0)
        if bonus_xp and not result.get('already_completed'):
            award_xp(user_id, bonus_xp, 'daily_challenge')
        return result
    except Exception:
        logger.exception("maybe_auto_complete_challenge failed for user=%s lesson=%s", user_id, lesson_id)
        return None
