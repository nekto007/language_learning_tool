"""Database queries for Telegram bot notifications."""
from datetime import datetime, timezone, timedelta, date
from typing import Any

from sqlalchemy import func

from app.utils.db import db
from app.curriculum.models import LessonProgress, Lessons, Module
from app.grammar_lab.models import UserGrammarExercise, UserGrammarTopicStatus, GrammarTopic
from app.study.models import UserWord, UserCardDirection
from app.books.models import UserChapterProgress, Book


def has_activity_today(user_id: int) -> bool:
    """Check if user had any learning activity today (UTC-based)."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Check lesson progress
    lesson_activity = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.last_activity >= today_start,
    ).first()
    if lesson_activity:
        return True

    # Check grammar exercises
    grammar_activity = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= today_start,
    ).first()
    if grammar_activity:
        return True

    # Check word reviews
    word_activity = db.session.query(UserCardDirection).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.last_reviewed >= today_start,
    ).first()
    if word_activity:
        return True

    # Check book reading
    book_activity = UserChapterProgress.query.filter(
        UserChapterProgress.user_id == user_id,
        UserChapterProgress.updated_at >= today_start,
    ).first()
    if book_activity:
        return True

    return False


def get_current_streak(user_id: int) -> int:
    """Calculate current streak (consecutive days with activity).

    Looks back from yesterday (today may still have activity ahead).
    """
    today = date.today()
    streak = 0

    # If there's activity today, count today
    if has_activity_today(user_id):
        streak = 1
        check_date = today - timedelta(days=1)
    else:
        check_date = today - timedelta(days=1)

    # Walk backwards through dates
    for _ in range(365):  # max lookback
        day_start = datetime(check_date.year, check_date.month, check_date.day,
                             tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        had_activity = False

        # Check lessons
        if LessonProgress.query.filter(
            LessonProgress.user_id == user_id,
            LessonProgress.last_activity >= day_start,
            LessonProgress.last_activity < day_end,
        ).first():
            had_activity = True

        # Check grammar
        if not had_activity and UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.last_reviewed >= day_start,
            UserGrammarExercise.last_reviewed < day_end,
        ).first():
            had_activity = True

        # Check words
        if not had_activity and db.session.query(UserCardDirection).join(UserWord).filter(
            UserWord.user_id == user_id,
            UserCardDirection.last_reviewed >= day_start,
            UserCardDirection.last_reviewed < day_end,
        ).first():
            had_activity = True

        if had_activity:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break

    return streak


def get_daily_plan(user_id: int) -> dict[str, Any]:
    """Build daily study plan: next lesson, grammar topic, SRS words due."""
    now = datetime.now(timezone.utc)

    # Next unfinished lesson
    next_lesson = None
    # Find last completed lesson, get the next one
    last_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
    ).order_by(LessonProgress.completed_at.desc()).first()

    if last_completed:
        lesson = Lessons.query.get(last_completed.lesson_id)
        if lesson:
            module = Module.query.get(lesson.module_id)
            if module:
                # Find next lesson in same module or next module
                next_l = Lessons.query.filter(
                    Lessons.module_id == module.id,
                    Lessons.order > lesson.order,
                ).order_by(Lessons.order).first()

                if not next_l:
                    # Try next module
                    next_module = Module.query.filter(
                        Module.number == module.number + 1,
                    ).first()
                    if next_module:
                        next_l = Lessons.query.filter(
                            Lessons.module_id == next_module.id,
                        ).order_by(Lessons.order).first()

                if next_l:
                    next_module = Module.query.get(next_l.module_id)
                    next_lesson = {
                        'title': next_l.title,
                        'module_number': next_module.number if next_module else None,
                        'lesson_order': next_l.order,
                    }

    # Grammar topic to practice
    grammar_topic = None
    active_status = UserGrammarTopicStatus.query.filter(
        UserGrammarTopicStatus.user_id == user_id,
        UserGrammarTopicStatus.status.in_(['theory_completed', 'practicing']),
    ).first()
    if active_status:
        topic = GrammarTopic.query.get(active_status.topic_id)
        # Count due exercises
        due_exercises = UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.exercise_id.in_(
                db.session.query(UserGrammarExercise.exercise_id).filter(
                    UserGrammarExercise.user_id == user_id,
                )
            ),
            UserGrammarExercise.next_review <= now,
        ).count()
        if topic:
            grammar_topic = {
                'title': topic.title,
                'status': active_status.status,
                'due_exercises': due_exercises,
            }

    # Words due for SRS review
    words_due = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.next_review <= now,
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    # Book reading — find active book not read today
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    book_to_read = None

    # Find books user has started reading (has chapter progress)
    from sqlalchemy import distinct
    from app.books.models import Chapter
    started_book_ids = db.session.query(distinct(Chapter.book_id)).join(
        UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id
    ).filter(UserChapterProgress.user_id == user_id).all()
    started_book_ids = [r[0] for r in started_book_ids]

    if started_book_ids:
        # Check if any of these books were NOT read today
        read_today_book_ids = db.session.query(distinct(Chapter.book_id)).join(
            UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id
        ).filter(
            UserChapterProgress.user_id == user_id,
            UserChapterProgress.updated_at >= today_start,
        ).all()
        read_today_book_ids = {r[0] for r in read_today_book_ids}

        not_read_today = [bid for bid in started_book_ids if bid not in read_today_book_ids]
        if not_read_today:
            book = Book.query.get(not_read_today[0])
            if book:
                book_to_read = {'title': book.title}

    # Onboarding suggestions for new users
    suggestions = []
    has_any_words = UserWord.query.filter_by(user_id=user_id).first() is not None
    has_any_lessons = LessonProgress.query.filter_by(user_id=user_id).first() is not None
    has_any_books = len(started_book_ids) > 0

    if not has_any_lessons:
        suggestions.append('Начни курс — структурированные уроки по уровням')
    if not has_any_words:
        suggestions.append('Добавь слова в карточки для повторения')
    if not has_any_books:
        suggestions.append('Выбери книгу для чтения с переводом')

    return {
        'next_lesson': next_lesson,
        'grammar_topic': grammar_topic,
        'words_due': words_due,
        'book_to_read': book_to_read,
        'suggestions': suggestions,
    }


def get_daily_summary(user_id: int) -> dict[str, Any]:
    """Get summary of today's activity."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Lessons completed today
    lessons_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        LessonProgress.completed_at >= today_start,
    ).all()

    lesson_titles = []
    for lp in lessons_completed:
        lesson = Lessons.query.get(lp.lesson_id)
        if lesson:
            lesson_titles.append(lesson.title)

    # Grammar exercises done today
    grammar_done = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= today_start,
    ).count()

    grammar_correct = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= today_start,
    ).with_entities(
        func.sum(UserGrammarExercise.correct_count)
    ).scalar() or 0

    # Words reviewed today
    words_reviewed = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    # Books read today
    from app.books.models import Chapter
    from sqlalchemy import distinct
    books_read_today = db.session.query(Book.title).join(
        Chapter, Chapter.book_id == Book.id
    ).join(
        UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id
    ).filter(
        UserChapterProgress.user_id == user_id,
        UserChapterProgress.updated_at >= today_start,
    ).distinct().all()
    book_titles = [r[0] for r in books_read_today]

    return {
        'lessons_completed': lesson_titles,
        'grammar_exercises': grammar_done,
        'grammar_correct': grammar_correct,
        'words_reviewed': words_reviewed,
        'books_read': book_titles,
    }


def get_weekly_report(user_id: int) -> dict[str, Any]:
    """Get weekly statistics for the report."""
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_week_start = week_start - timedelta(days=7)

    def _count_active_days(start: datetime, end: datetime) -> int:
        """Count days with at least one activity."""
        active_days = set()
        # Lesson activity
        for lp in LessonProgress.query.filter(
            LessonProgress.user_id == user_id,
            LessonProgress.last_activity >= start,
            LessonProgress.last_activity < end,
        ).all():
            if lp.last_activity:
                active_days.add(lp.last_activity.date())

        # Grammar activity
        for ge in UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.last_reviewed >= start,
            UserGrammarExercise.last_reviewed < end,
        ).all():
            if ge.last_reviewed:
                active_days.add(ge.last_reviewed.date())

        # Word reviews
        for row in db.session.query(UserCardDirection.last_reviewed).join(UserWord).filter(
            UserWord.user_id == user_id,
            UserCardDirection.last_reviewed >= start,
            UserCardDirection.last_reviewed < end,
            UserCardDirection.direction == 'eng-rus',
        ).all():
            if row[0]:
                active_days.add(row[0].date())

        return len(active_days)

    active_days = _count_active_days(week_start, now)
    prev_active_days = _count_active_days(prev_week_start, week_start)

    # Lessons completed this week
    lessons_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        LessonProgress.completed_at >= week_start,
    ).count()

    prev_lessons = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        LessonProgress.completed_at >= prev_week_start,
        LessonProgress.completed_at < week_start,
    ).count()

    # Grammar exercises
    exercises_done = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= week_start,
    ).count()

    # Words in SRS
    words_in_srs = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.state != 'new',
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    streak = get_current_streak(user_id)

    return {
        'week_start': week_start.date(),
        'week_end': now.date(),
        'active_days': active_days,
        'prev_active_days': prev_active_days,
        'lessons_completed': lessons_completed,
        'prev_lessons': prev_lessons,
        'exercises_done': exercises_done,
        'words_in_srs': words_in_srs,
        'streak': streak,
    }


def get_quick_stats(user_id: int) -> dict[str, Any]:
    """Quick stats for /stats command."""
    now = datetime.now(timezone.utc)

    lessons_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
    ).count()

    exercises_done = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed.isnot(None),
    ).count()

    words_in_srs = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.state != 'new',
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    streak = get_current_streak(user_id)

    return {
        'streak': streak,
        'lessons_completed': lessons_completed,
        'exercises_done': exercises_done,
        'words_in_srs': words_in_srs,
    }
