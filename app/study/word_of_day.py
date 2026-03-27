"""Word of the Day — picks a word from user's current book/course with context."""
from __future__ import annotations

from datetime import date, datetime, timezone
from random import Random

from app.utils.db import db


def get_word_of_day(user_id: int) -> dict | None:
    """Pick today's word for a user. Deterministic per user+date (same word all day)."""
    from app.study.models import UserWord, UserCardDirection
    from app.words.models import CollectionWords
    from app.curriculum.daily_lessons import SliceVocabulary, DailyLesson
    from app.curriculum.book_courses import BookCourseEnrollment, BookCourseModule

    # Seed random with user_id + today's date for deterministic pick
    seed = user_id * 10000 + date.today().toordinal()
    rng = Random(seed)

    # Strategy 1: Pick from current book course vocabulary (most contextual)
    enrollment = BookCourseEnrollment.query.filter_by(
        user_id=user_id, status='active',
    ).first()
    if enrollment:
        # Get vocab from recent modules (last 3)
        modules = BookCourseModule.query.filter_by(
            course_id=enrollment.course_id,
        ).order_by(BookCourseModule.module_number.desc()).limit(3).all()

        if modules:
            module_ids = [m.id for m in modules]
            vocab_items = db.session.query(
                SliceVocabulary, CollectionWords,
            ).join(
                DailyLesson, DailyLesson.id == SliceVocabulary.daily_lesson_id,
            ).join(
                CollectionWords, CollectionWords.id == SliceVocabulary.word_id,
            ).filter(
                DailyLesson.book_course_module_id.in_(module_ids),
                SliceVocabulary.is_new == True,  # noqa: E712
            ).all()

            if vocab_items:
                sv, cw = rng.choice(vocab_items)
                return {
                    'word': cw.english_word,
                    'translation': cw.russian_word,
                    'context_sentence': sv.context_sentence or '',
                    'source': 'book_course',
                }

    # Strategy 2: Pick from user's SRS words that need review
    overdue = db.session.query(CollectionWords).join(
        UserWord, UserWord.word_id == CollectionWords.id,
    ).join(
        UserCardDirection, UserCardDirection.user_word_id == UserWord.id,
    ).filter(
        UserWord.user_id == user_id,
        UserCardDirection.direction == 'eng-rus',
        UserCardDirection.next_review <= datetime.now(timezone.utc),
    ).limit(20).all()

    if overdue:
        word = rng.choice(overdue)
        return {
            'word': word.english_word,
            'translation': word.russian_word,
            'context_sentence': word.sentences or '',
            'source': 'srs_overdue',
        }

    return None
