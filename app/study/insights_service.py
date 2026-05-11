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
from config.settings import DEFAULT_TIMEZONE


# ---------------------------------------------------------------------------
# 1. Activity heatmap
# ---------------------------------------------------------------------------

def get_activity_heatmap(user_id: int, days: int = 90,
                         tz: str = DEFAULT_TIMEZONE) -> list[dict[str, Any]]:
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
                        tz: str = DEFAULT_TIMEZONE) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# Listening stats (last 7 days)
# ---------------------------------------------------------------------------

def get_listening_stats(user_id: int) -> dict[str, Any]:
    """Return listening analytics for the last 7 days.

    Keys:
      - total_lessons: distinct lesson_ids with at least one attempt (all time)
      - avg_score: average score across all attempts in the last 7 days (0 if none)
      - total_replays: sum of replay_count in the last 7 days
    """
    from app.curriculum.models import ListeningAttempt

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # All-time distinct lesson count for this user.
    total_lessons = (
        db.session.query(func.count(func.distinct(ListeningAttempt.lesson_id)))
        .filter(ListeningAttempt.user_id == user_id)
        .scalar()
    ) or 0

    # Last-7-days aggregates.
    row = (
        db.session.query(
            func.avg(ListeningAttempt.score).label('avg_score'),
            func.coalesce(func.sum(ListeningAttempt.replay_count), 0).label('total_replays'),
        )
        .filter(
            ListeningAttempt.user_id == user_id,
            ListeningAttempt.created_at >= seven_days_ago,
        )
        .one()
    )

    avg_score = round(float(row.avg_score), 1) if row.avg_score is not None else 0.0
    total_replays = int(row.total_replays)

    return {
        'total_lessons': int(total_lessons),
        'avg_score': avg_score,
        'total_replays': total_replays,
    }


# ---------------------------------------------------------------------------
# Writing stats
# ---------------------------------------------------------------------------

def get_writing_stats(user_id: int) -> dict[str, Any]:
    """Return writing analytics for the user.

    Keys:
      - total_attempts: all-time count of UserWritingAttempt rows
      - avg_word_count: average word_count across all attempts (0 if none)
      - consecutive_days: streak of consecutive calendar days with at least one attempt
    """
    from app.curriculum.models import UserWritingAttempt

    agg = (
        db.session.query(
            func.count(UserWritingAttempt.id).label('total'),
            func.avg(UserWritingAttempt.word_count).label('avg_words'),
        )
        .filter(UserWritingAttempt.user_id == user_id)
        .one()
    )

    total_attempts = int(agg.total) if agg.total else 0
    avg_word_count = round(float(agg.avg_words), 1) if agg.avg_words is not None else 0.0

    # Consecutive days streak (most recent run ending today or yesterday).
    day_rows = (
        db.session.query(
            cast(UserWritingAttempt.created_at, Date).label('d'),
        )
        .filter(UserWritingAttempt.user_id == user_id)
        .distinct()
        .all()
    )
    active_dates = {row.d for row in day_rows}

    today = date.today()
    consecutive_days = 0
    if active_dates:
        anchor = today if today in active_dates else today - timedelta(days=1)
        if anchor in active_dates:
            check = anchor
            while check in active_dates:
                consecutive_days += 1
                check -= timedelta(days=1)

    return {
        'total_attempts': total_attempts,
        'avg_word_count': avg_word_count,
        'consecutive_days': consecutive_days,
    }


# ---------------------------------------------------------------------------
# Vocabulary growth (new cards added per day)
# ---------------------------------------------------------------------------

def get_vocabulary_growth(user_id: int, days: int = 30) -> dict[str, Any]:
    """Count new UserWord rows added per day over the last *days* days.

    Returns:
      - dates: list of ISO date strings (oldest first, length == days)
      - counts: list of int counts aligned with dates
      - total_active: total UserCardDirection rows with state != 'new'
      - words_this_week: sum of counts over the last 7 entries
    """
    from app.study.models import UserWord, UserCardDirection

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Count new UserWord rows per UTC calendar day.
    rows = (
        db.session.query(
            cast(UserWord.created_at, Date).label('d'),
            func.count(UserWord.id).label('cnt'),
        )
        .filter(
            UserWord.user_id == user_id,
            UserWord.created_at >= cutoff,
        )
        .group_by(cast(UserWord.created_at, Date))
        .all()
    )

    counts_by_date: dict[date, int] = {row.d: int(row.cnt) for row in rows}

    today = date.today()
    dates: list[str] = []
    counts: list[int] = []
    for offset in range(days):
        d = today - timedelta(days=days - 1 - offset)
        dates.append(d.isoformat())
        counts.append(counts_by_date.get(d, 0))

    # Active cards: state is not 'new' (has been reviewed at least once).
    total_active = (
        db.session.query(func.count(UserCardDirection.id))
        .join(UserWord, UserCardDirection.user_word_id == UserWord.id)
        .filter(
            UserWord.user_id == user_id,
            UserCardDirection.state != 'new',
        )
        .scalar()
    ) or 0

    words_this_week = sum(counts[-7:])

    return {
        'dates': dates,
        'counts': counts,
        'total_active': int(total_active),
        'words_this_week': words_this_week,
    }


# ---------------------------------------------------------------------------
# Weekly summary (week-to-date, NOT lifetime)
# ---------------------------------------------------------------------------

def get_weekly_summary(user_id: int) -> dict[str, Any]:
    """Week-to-date learning stats for the dashboard 'This Week' card.

    Returns words_reviewed, lessons_completed, time_minutes, accuracy.
    """
    from app.study.models import StudySession
    from app.curriculum.models import LessonProgress, LessonAttempt

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    # Words reviewed this week (from StudySession)
    row = (
        db.session.query(
            func.coalesce(func.sum(StudySession.words_studied), 0),
            func.coalesce(func.sum(StudySession.correct_answers), 0),
            func.coalesce(func.sum(StudySession.incorrect_answers), 0),
        )
        .filter(StudySession.user_id == user_id, StudySession.start_time >= week_ago)
        .one()
    )
    words_reviewed = int(row[0])
    correct = int(row[1])
    incorrect = int(row[2])
    accuracy = round(correct / (correct + incorrect) * 100) if (correct + incorrect) > 0 else 0

    # Lessons completed this week
    lessons_completed = (
        LessonProgress.query
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            LessonProgress.completed_at >= week_ago,
        )
        .count()
    )

    # Time spent (lesson attempts + study sessions)
    lesson_time = (
        db.session.query(func.coalesce(func.sum(LessonAttempt.time_spent_seconds), 0))
        .filter(LessonAttempt.user_id == user_id, LessonAttempt.started_at >= week_ago)
        .scalar()
    )
    study_time = (
        db.session.query(
            func.coalesce(
                func.sum(func.extract('epoch', StudySession.end_time) - func.extract('epoch', StudySession.start_time)),
                0,
            )
        )
        .filter(
            StudySession.user_id == user_id,
            StudySession.start_time >= week_ago,
            StudySession.end_time.isnot(None),
        )
        .scalar()
    )
    time_minutes = round((int(lesson_time) + int(study_time)) / 60)

    return {
        'words_reviewed': words_reviewed,
        'lessons_completed': lessons_completed,
        'time_minutes': time_minutes,
        'accuracy': accuracy,
    }


# ---------------------------------------------------------------------------
# Pronunciation weaknesses
# ---------------------------------------------------------------------------

def get_pronunciation_stats(user_id: int) -> dict[str, Any]:
    """Return pronunciation analytics.

    Keys:
      - total_attempts: all-time count of PronunciationAttempt rows
      - total_words: distinct words practiced (all time)
      - match_rate_7d: percentage of matched attempts in the last 7 days (0.0 if none)
    """
    from app.curriculum.models import PronunciationAttempt

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    total_attempts = (
        db.session.query(func.count(PronunciationAttempt.id))
        .filter(PronunciationAttempt.user_id == user_id)
        .scalar()
    ) or 0

    total_words = (
        db.session.query(func.count(func.distinct(PronunciationAttempt.word)))
        .filter(PronunciationAttempt.user_id == user_id)
        .scalar()
    ) or 0

    row_7d = (
        db.session.query(
            func.count(PronunciationAttempt.id).label('total'),
            func.sum(
                func.cast(PronunciationAttempt.matched, db.Integer)
            ).label('matched'),
        )
        .filter(
            PronunciationAttempt.user_id == user_id,
            PronunciationAttempt.created_at >= seven_days_ago,
        )
        .one()
    )

    total_7d = int(row_7d.total) if row_7d.total else 0
    matched_7d = int(row_7d.matched) if row_7d.matched else 0
    match_rate_7d = round(matched_7d / total_7d * 100, 1) if total_7d > 0 else 0.0

    return {
        'total_attempts': int(total_attempts),
        'total_words': int(total_words),
        'match_rate_7d': match_rate_7d,
    }


def get_pronunciation_weaknesses(user_id: int, min_attempts: int = 3) -> list[str]:
    """Return words where match_rate < 50% across all pronunciation attempts.

    Only includes words with at least *min_attempts* total attempts.
    Returns a sorted list of word strings.
    """
    from sqlalchemy import Integer, cast, case
    from app.curriculum.models import PronunciationAttempt

    rows = (
        db.session.query(
            PronunciationAttempt.word,
            func.count(PronunciationAttempt.id).label('total'),
            func.sum(
                cast(
                    case((PronunciationAttempt.matched == True, 1), else_=0),
                    Integer,
                )
            ).label('matched_count'),
        )
        .filter(PronunciationAttempt.user_id == user_id)
        .group_by(PronunciationAttempt.word)
        .having(func.count(PronunciationAttempt.id) >= min_attempts)
        .all()
    )

    weak_words = []
    for row in rows:
        total = int(row.total)
        matched = int(row.matched_count) if row.matched_count is not None else 0
        match_rate = matched / total if total > 0 else 0.0
        if match_rate < 0.5:
            weak_words.append(row.word)

    return sorted(weak_words)
