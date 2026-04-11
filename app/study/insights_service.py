# app/study/insights_service.py
"""
Learning Insights analytics service.

Computes learning analytics from existing data — no new DB tables needed.
All functions accept user_id and return dicts/lists safe for JSON serialization.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Date, cast, func, extract

from app.utils.db import db


# ---------------------------------------------------------------------------
# 1. Activity heatmap
# ---------------------------------------------------------------------------

def get_activity_heatmap(user_id: int, days: int = 90,
                         tz: str = 'Europe/Moscow') -> list[dict[str, Any]]:
    """
    Return list of ``{date: "2026-03-27", count: N}`` for the last *days* days.

    ``count`` = total number of activity records across all sources that day
    (timezone-adjusted to *tz*):
      - curriculum lesson completion  (LessonProgress.completed_at)
      - grammar SRS review            (UserGrammarExercise.last_reviewed)
      - flashcard review               (UserCardDirection.last_reviewed)
      - book chapter reading           (UserChapterProgress.updated_at)
      - daily-lesson completion        (UserLessonProgress.completed_at)
    """
    from app.curriculum.models import LessonProgress
    from app.grammar_lab.models import UserGrammarExercise
    from app.study.models import UserCardDirection
    from app.books.models import UserChapterProgress
    from app.curriculum.daily_lessons import UserLessonProgress

    # Add +1 day buffer so timezone-ahead users don't lose boundary-day data.
    start_date = datetime.now(timezone.utc) - timedelta(days=days + 1)

    def _local_date(col):
        """Cast a UTC timestamp column to a local date in the target tz."""
        return cast(func.timezone(tz, func.timezone('UTC', col)), Date)

    # Each sub-query returns (local_date, record_count) per day.

    # -- curriculum lessons --
    q1 = (
        db.session.query(
            _local_date(LessonProgress.completed_at).label('d'),
            func.count().label('cnt'),
        )
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.completed_at >= start_date,
            LessonProgress.completed_at.isnot(None),
        )
        .group_by(_local_date(LessonProgress.completed_at))
    )

    # -- grammar SRS --
    q2 = (
        db.session.query(
            _local_date(UserGrammarExercise.last_reviewed).label('d'),
            func.count().label('cnt'),
        )
        .filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.last_reviewed >= start_date,
            UserGrammarExercise.last_reviewed.isnot(None),
        )
        .group_by(_local_date(UserGrammarExercise.last_reviewed))
    )

    # -- flashcards --
    from app.study.models import UserWord

    q3 = (
        db.session.query(
            _local_date(UserCardDirection.last_reviewed).label('d'),
            func.count().label('cnt'),
        )
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.last_reviewed >= start_date,
            UserCardDirection.last_reviewed.isnot(None),
        )
        .group_by(_local_date(UserCardDirection.last_reviewed))
    )

    # -- book chapter progress --
    q4 = (
        db.session.query(
            _local_date(UserChapterProgress.updated_at).label('d'),
            func.count().label('cnt'),
        )
        .filter(
            UserChapterProgress.user_id == user_id,
            UserChapterProgress.updated_at >= start_date,
            UserChapterProgress.updated_at.isnot(None),
        )
        .group_by(_local_date(UserChapterProgress.updated_at))
    )

    # -- daily lesson progress --
    q5 = (
        db.session.query(
            _local_date(UserLessonProgress.completed_at).label('d'),
            func.count().label('cnt'),
        )
        .filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.completed_at >= start_date,
            UserLessonProgress.completed_at.isnot(None),
        )
        .group_by(_local_date(UserLessonProgress.completed_at))
    )

    # UNION ALL, then sum record counts per day.
    union = q1.union_all(q2, q3, q4, q5).subquery()

    rows = (
        db.session.query(
            union.c.d,
            func.sum(union.c.cnt),
        )
        .group_by(union.c.d)
        .all()
    )

    counts_by_date: dict[date, int] = {row[0]: int(row[1]) for row in rows}

    # Build the full range so the frontend always gets every day.
    # Use timezone-aware "today" so dates align with the DB grouping.
    import pytz as _pytz
    try:
        today = datetime.now(_pytz.timezone(tz)).date()
    except Exception:
        today = date.today()
    result: list[dict[str, Any]] = []
    for offset in range(days):
        d = today - timedelta(days=days - 1 - offset)
        result.append({
            'date': d.isoformat(),
            'count': counts_by_date.get(d, 0),
        })

    return result


# ---------------------------------------------------------------------------
# 2. Best study time
# ---------------------------------------------------------------------------

def get_best_study_time(user_id: int,
                        tz: str = 'Europe/Moscow') -> dict[str, Any]:
    """
    Return ``{best_hour: 14, hourly_scores: {9: 82.5, 14: 91.2, ...}}``.

    Based on LessonProgress where score is not null, grouped by hour of
    ``completed_at`` converted to the user's timezone *tz*.
    """
    from app.curriculum.models import LessonProgress

    # Convert UTC timestamp to local timezone before extracting hour
    local_completed = func.timezone(tz, func.timezone('UTC', LessonProgress.completed_at))

    rows = (
        db.session.query(
            extract('hour', local_completed).label('hour'),
            func.avg(LessonProgress.score).label('avg_score'),
        )
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.score.isnot(None),
            LessonProgress.completed_at.isnot(None),
        )
        .group_by(extract('hour', local_completed))
        .all()
    )

    if not rows:
        return {'best_hour': None, 'hourly_scores': {}}

    hourly_scores: dict[int, float] = {
        int(row.hour): round(float(row.avg_score), 1) for row in rows
    }
    best_hour = max(hourly_scores, key=hourly_scores.get)  # type: ignore[arg-type]

    return {
        'best_hour': best_hour,
        'hourly_scores': hourly_scores,
    }


# ---------------------------------------------------------------------------
# 3. Words at risk (overdue for review)
# ---------------------------------------------------------------------------

def get_words_at_risk(user_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """
    Return words most overdue for review.

    Queries ``UserCardDirection`` where ``next_review < now`` and
    ``direction = 'eng-rus'``, joined with ``UserWord`` and
    ``CollectionWords`` for display data.
    """
    from app.study.models import UserCardDirection, UserWord
    from app.words.models import CollectionWords

    now = datetime.now(timezone.utc)

    rows = (
        db.session.query(
            CollectionWords.english_word,
            CollectionWords.russian_word,
            UserCardDirection.next_review,
        )
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .join(CollectionWords, UserWord.word_id == CollectionWords.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.direction == 'eng-rus',
            UserCardDirection.next_review < now,
            UserCardDirection.next_review.isnot(None),
            # Only cards that have been reviewed at least once
            UserCardDirection.last_reviewed.isnot(None),
        )
        .order_by(UserCardDirection.next_review.asc())
        .limit(limit)
        .all()
    )

    result: list[dict[str, Any]] = []
    for row in rows:
        next_rev = row.next_review
        if next_rev.tzinfo is None:
            next_rev = next_rev.replace(tzinfo=timezone.utc)
        days_overdue = (now - next_rev).days
        result.append({
            'word': row.english_word,
            'translation': row.russian_word or '',
            'days_overdue': max(0, days_overdue),
        })

    return result


# ---------------------------------------------------------------------------
# 4. Grammar weaknesses
# ---------------------------------------------------------------------------

def get_grammar_weaknesses(user_id: int, limit: int = 5) -> list[dict[str, Any]]:
    """
    Return grammar topics with the lowest accuracy.

    Accuracy = ``correct_count / (correct_count + incorrect_count)`` across
    all ``UserGrammarExercise`` rows for the topic.  Only topics with at
    least 3 attempts are included.
    """
    from app.grammar_lab.models import UserGrammarExercise, GrammarExercise, GrammarTopic

    total_expr = func.sum(UserGrammarExercise.correct_count + UserGrammarExercise.incorrect_count)
    accuracy_expr = (
        func.sum(UserGrammarExercise.correct_count) * 100.0 / total_expr
    )

    rows = (
        db.session.query(
            GrammarTopic.title,
            accuracy_expr.label('accuracy'),
            total_expr.label('attempts'),
        )
        .join(GrammarExercise, GrammarExercise.topic_id == GrammarTopic.id)
        .join(
            UserGrammarExercise,
            UserGrammarExercise.exercise_id == GrammarExercise.id,
        )
        .filter(UserGrammarExercise.user_id == user_id)
        .group_by(GrammarTopic.id, GrammarTopic.title)
        .having(total_expr >= 3)
        .order_by(accuracy_expr.asc())
        .limit(limit)
        .all()
    )

    return [
        {
            'title': row.title,
            'accuracy': round(float(row.accuracy), 1),
            'attempts': int(row.attempts),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# 5. Reading speed trend
# ---------------------------------------------------------------------------

def get_reading_speed_trend(user_id: int) -> list[dict[str, Any]]:
    """
    Return weekly reading-speed trend from book-course daily lessons.

    For each completed reading lesson that has both ``word_count`` and
    ``time_spent`` (> 0), compute ``wpm = word_count / (time_spent / 60)``.
    Group by ISO week and return ``[{week: "2026-W12", avg_wpm: 120}, ...]``.
    """
    from app.curriculum.daily_lessons import DailyLesson, UserLessonProgress

    rows = (
        db.session.query(
            UserLessonProgress.completed_at,
            DailyLesson.word_count,
            UserLessonProgress.time_spent,
        )
        .join(DailyLesson, UserLessonProgress.daily_lesson_id == DailyLesson.id)
        .filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.status == 'completed',
            UserLessonProgress.completed_at.isnot(None),
            UserLessonProgress.time_spent > 0,
            DailyLesson.lesson_type == 'reading',
            DailyLesson.word_count > 0,
        )
        .order_by(UserLessonProgress.completed_at)
        .all()
    )

    if not rows:
        return []

    # Accumulate per ISO-week.
    weekly: dict[str, list[float]] = {}
    for row in rows:
        completed_at = row.completed_at
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)
        iso_cal = completed_at.isocalendar()
        week_key = f'{iso_cal[0]}-W{iso_cal[1]:02d}'

        wpm = (row.word_count / row.time_spent) * 60  # time_spent is seconds
        weekly.setdefault(week_key, []).append(wpm)

    return [
        {
            'week': week,
            'avg_wpm': round(sum(vals) / len(vals), 1),
        }
        for week, vals in weekly.items()
    ]


# ---------------------------------------------------------------------------
# 6. Learning summary
# ---------------------------------------------------------------------------

def get_learning_summary(user_id: int) -> dict[str, Any]:
    """
    High-level stats:
      - total_words_learned (UserWord with status != 'new')
      - total_words_review  (UserWord with status == 'review')
      - total_lessons       (completed LessonProgress)
      - total_book_lessons  (completed UserLessonProgress)
      - total_hours         (sum of time from LessonAttempt + UserLessonProgress)
      - books_enrolled      (BookCourseEnrollment count)
      - grammar_topics_practiced (UserGrammarTopicStatus with status != 'new')
      - current_streak_days
    """
    from app.curriculum.models import LessonProgress, LessonAttempt
    from app.study.models import UserWord
    from app.grammar_lab.models import UserGrammarTopicStatus
    from app.curriculum.daily_lessons import UserLessonProgress
    from app.curriculum.book_courses import BookCourseEnrollment

    # --- words ---
    word_stats = (
        db.session.query(
            func.count(UserWord.id).label('total'),
            func.count(UserWord.id).filter(UserWord.status != 'new').label('learned'),
            func.count(UserWord.id).filter(UserWord.status == 'review').label('review'),
        )
        .filter(UserWord.user_id == user_id)
        .first()
    )

    # --- curriculum lessons ---
    lessons_completed = (
        db.session.query(func.count(LessonProgress.id))
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        )
        .scalar()
    ) or 0

    # --- book-course lessons ---
    book_lessons_completed = (
        db.session.query(func.count(UserLessonProgress.id))
        .filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.status == 'completed',
        )
        .scalar()
    ) or 0

    # --- total hours (curriculum attempts + book-course lessons) ---
    curriculum_seconds = (
        db.session.query(func.coalesce(func.sum(LessonAttempt.time_spent_seconds), 0))
        .filter(
            LessonAttempt.user_id == user_id,
            LessonAttempt.time_spent_seconds.isnot(None),
        )
        .scalar()
    ) or 0

    book_seconds = (
        db.session.query(func.coalesce(func.sum(UserLessonProgress.time_spent), 0))
        .filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.time_spent.isnot(None),
        )
        .scalar()
    ) or 0

    total_hours = round((curriculum_seconds + book_seconds) / 3600, 1)

    # --- books enrolled ---
    books_enrolled = (
        db.session.query(func.count(BookCourseEnrollment.id))
        .filter(BookCourseEnrollment.user_id == user_id)
        .scalar()
    ) or 0

    # --- grammar topics ---
    grammar_topics_practiced = (
        db.session.query(func.count(UserGrammarTopicStatus.id))
        .filter(
            UserGrammarTopicStatus.user_id == user_id,
            UserGrammarTopicStatus.status != 'new',
        )
        .scalar()
    ) or 0

    # --- current streak (consecutive days with any completed activity) ---
    current_streak = _compute_current_streak(user_id)

    return {
        'total_words_learned': word_stats.learned if word_stats else 0,
        'total_words_review': word_stats.review if word_stats else 0,
        'total_lessons': lessons_completed + book_lessons_completed,
        'total_hours': total_hours,
        'books_enrolled': books_enrolled,
        'grammar_topics_practiced': grammar_topics_practiced,
        'current_streak_days': current_streak,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_current_streak(user_id: int) -> int:
    """
    Count consecutive days (ending today or yesterday) on which the user
    had at least one completed activity.  Uses LessonProgress.completed_at
    and UserLessonProgress.completed_at as activity sources.
    """
    from app.curriculum.models import LessonProgress
    from app.curriculum.daily_lessons import UserLessonProgress

    # Collect distinct dates from both tables.
    q1 = (
        db.session.query(cast(LessonProgress.completed_at, Date).label('d'))
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.completed_at.isnot(None),
        )
    )
    q2 = (
        db.session.query(cast(UserLessonProgress.completed_at, Date).label('d'))
        .filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.completed_at.isnot(None),
        )
    )

    union = q1.union(q2).subquery()
    rows = (
        db.session.query(union.c.d)
        .distinct()
        .order_by(union.c.d.desc())
        .all()
    )

    if not rows:
        return 0

    active_dates = {row[0] for row in rows}
    today = date.today()

    # Streak must include today or yesterday to be "current".
    if today not in active_dates and (today - timedelta(days=1)) not in active_dates:
        return 0

    streak = 0
    check = today if today in active_dates else today - timedelta(days=1)
    while check in active_dates:
        streak += 1
        check -= timedelta(days=1)

    return streak
