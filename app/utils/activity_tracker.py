"""Canonical learning-activity check.

Single source of truth for "did this user do any learning between A and B?".
Used by streak service, telegram queries, admin DAU computation. Checks 6
activity sources so all callers count the same set of users.

Sources:
- LessonProgress.last_activity (curriculum lessons)
- UserGrammarExercise.last_reviewed (grammar exercises)
- UserCardDirection.last_reviewed (SRS card reviews, via UserWord join)
- UserChapterProgress.updated_at (book reading)
- UserLessonProgress.completed_at (book-course daily lessons)
- StudySession.start_time (flashcard study sessions)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _to_naive_utc(dt: datetime) -> datetime:
    """Strip tzinfo, converting to UTC first if aware."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def _to_aware_utc(dt: datetime) -> datetime:
    """Attach UTC tzinfo if naive (treats naive as UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def has_learning_activity(user_id: int, start_utc: datetime,
                          end_utc: datetime, db_session: Any = None) -> bool:
    """Return True if user had any learning activity in [start_utc, end_utc).

    Boundaries can be naive (assumed UTC) or tz-aware. Comparisons are
    issued in the column's native form: naive for naive columns, aware
    for tz-aware columns.

    Args:
        user_id: user to check
        start_utc: lower bound, inclusive
        end_utc: upper bound, exclusive
        db_session: optional SQLAlchemy session (defaults to app.utils.db.db.session)

    Returns:
        True on first activity match; False if no source matches.
    """
    from app.utils.db import db
    from app.curriculum.models import LessonProgress
    from app.curriculum.daily_lessons import UserLessonProgress
    from app.grammar_lab.models import UserGrammarExercise
    from app.study.models import UserWord, UserCardDirection, StudySession
    from app.books.models import UserChapterProgress

    session = db_session if db_session is not None else db.session

    start_naive = _to_naive_utc(start_utc)
    end_naive = _to_naive_utc(end_utc)
    start_aware = _to_aware_utc(start_utc)
    end_aware = _to_aware_utc(end_utc)

    # 1. Curriculum lessons (naive)
    if session.query(LessonProgress.id).filter(
        LessonProgress.user_id == user_id,
        LessonProgress.last_activity.isnot(None),
        LessonProgress.last_activity >= start_naive,
        LessonProgress.last_activity < end_naive,
    ).first():
        return True

    # 2. Grammar exercises (naive)
    if session.query(UserGrammarExercise.id).filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed.isnot(None),
        UserGrammarExercise.last_reviewed >= start_naive,
        UserGrammarExercise.last_reviewed < end_naive,
    ).first():
        return True

    # 3. SRS card reviews (naive, via UserWord join)
    if session.query(UserCardDirection.id).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.last_reviewed.isnot(None),
        UserCardDirection.last_reviewed >= start_naive,
        UserCardDirection.last_reviewed < end_naive,
    ).first():
        return True

    # 4. Book reading (naive). Composite PK; project an existing column.
    if session.query(UserChapterProgress.user_id).filter(
        UserChapterProgress.user_id == user_id,
        UserChapterProgress.updated_at >= start_naive,
        UserChapterProgress.updated_at < end_naive,
    ).first():
        return True

    # 5. Book-course daily lessons (TZ-AWARE column)
    if session.query(UserLessonProgress.id).filter(
        UserLessonProgress.user_id == user_id,
        UserLessonProgress.completed_at.isnot(None),
        UserLessonProgress.completed_at >= start_aware,
        UserLessonProgress.completed_at < end_aware,
    ).first():
        return True

    # 6. Flashcard study sessions (naive)
    if session.query(StudySession.id).filter(
        StudySession.user_id == user_id,
        StudySession.start_time >= start_naive,
        StudySession.start_time < end_naive,
    ).first():
        return True

    return False
