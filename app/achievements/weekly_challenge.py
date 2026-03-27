"""Weekly challenge -- rotates every Monday, computed from existing data."""
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.utils.db import db


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

    return {**challenge, 'current': current, 'week_start': week_start.isoformat()}


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
