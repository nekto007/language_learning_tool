"""Database queries for Telegram bot notifications."""
from datetime import datetime, timezone, timedelta, date
from typing import Any

import pytz
from sqlalchemy import func

from app.utils.db import db
from app.curriculum.models import LessonProgress, Lessons, Module
from app.grammar_lab.models import UserGrammarExercise, UserGrammarTopicStatus, GrammarTopic
from app.study.models import UserWord, UserCardDirection
from app.books.models import UserChapterProgress, Book
from app.telegram.notifications import LESSON_TIME

DEFAULT_TZ = 'Europe/Moscow'


def _user_day_boundaries(tz_name: str = DEFAULT_TZ,
                         offset_days: int = 0) -> tuple[datetime, datetime]:
    """Return (start_utc, end_utc) for 'today' in user's timezone.

    offset_days=-1 means yesterday in user's timezone, etc.
    """
    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        tz = pytz.timezone(DEFAULT_TZ)

    local_now = datetime.now(tz)
    local_day = local_now.date() + timedelta(days=offset_days)
    local_start = tz.localize(datetime(local_day.year, local_day.month, local_day.day))
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(pytz.utc), local_end.astimezone(pytz.utc)


def has_activity_today(user_id: int, tz: str = DEFAULT_TZ) -> bool:
    """Check if user had any learning activity today in their timezone."""
    today_start, today_end = _user_day_boundaries(tz)

    # Check lesson progress
    lesson_activity = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.last_activity >= today_start,
        LessonProgress.last_activity < today_end,
    ).first()
    if lesson_activity:
        return True

    # Check grammar exercises
    grammar_activity = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= today_start,
        UserGrammarExercise.last_reviewed < today_end,
    ).first()
    if grammar_activity:
        return True

    # Check word reviews
    word_activity = db.session.query(UserCardDirection).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.last_reviewed < today_end,
    ).first()
    if word_activity:
        return True

    # Check book reading
    book_activity = UserChapterProgress.query.filter(
        UserChapterProgress.user_id == user_id,
        UserChapterProgress.updated_at >= today_start,
        UserChapterProgress.updated_at < today_end,
    ).first()
    if book_activity:
        return True

    return False


def _has_activity_in_range(user_id: int, start_utc: datetime,
                           end_utc: datetime) -> bool:
    """Check if user had any activity between start_utc and end_utc."""
    if LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.last_activity >= start_utc,
        LessonProgress.last_activity < end_utc,
    ).first():
        return True

    if UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= start_utc,
        UserGrammarExercise.last_reviewed < end_utc,
    ).first():
        return True

    if db.session.query(UserCardDirection).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.last_reviewed >= start_utc,
        UserCardDirection.last_reviewed < end_utc,
    ).first():
        return True

    return False


def get_current_streak(user_id: int, tz: str = DEFAULT_TZ) -> int:
    """Calculate current streak (consecutive days with activity).

    Uses user's timezone to determine day boundaries.
    Looks back from yesterday (today may still have activity ahead).
    """
    streak = 0

    # If there's activity today, count today
    if has_activity_today(user_id, tz=tz):
        streak = 1

    # Walk backwards through dates (starting from yesterday)
    for offset in range(1, 366):
        day_start, day_end = _user_day_boundaries(tz, offset_days=-offset)

        if _has_activity_in_range(user_id, day_start, day_end):
            streak += 1
        else:
            break

    return streak


def get_daily_plan(user_id: int, tz: str = DEFAULT_TZ) -> dict[str, Any]:
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
                    level_code = None
                    if next_module and next_module.level:
                        level_code = next_module.level.code
                    next_lesson = {
                        'title': next_l.title,
                        'module_number': next_module.number if next_module else None,
                        'lesson_order': next_l.order,
                        'lesson_type': next_l.type,
                        'lesson_id': next_l.id,
                        'level_code': level_code,
                    }

    # Grammar topic to practice — prefer topic from current module
    grammar_topic = None
    current_module_id = None
    if next_lesson and next_lesson.get('lesson_id'):
        planned_lesson = Lessons.query.get(next_lesson['lesson_id'])
        if planned_lesson:
            current_module_id = planned_lesson.module_id

    # Collect grammar topic IDs linked to current module's lessons
    module_topic_ids: list[int] = []
    if current_module_id:
        module_topic_ids = [
            row[0] for row in db.session.query(Lessons.grammar_topic_id).filter(
                Lessons.module_id == current_module_id,
                Lessons.grammar_topic_id.isnot(None),
            ).all()
        ]

    def _build_grammar_dict(topic: GrammarTopic, status_str: str) -> dict[str, Any]:
        due = UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.next_review <= now,
        ).count() if status_str != 'not_started' else 0
        return {
            'title': topic.title,
            'status': status_str,
            'due_exercises': due,
            'topic_id': topic.id,
            'telegram_summary': topic.telegram_summary,
        }

    # 1) Active topic from current module
    if module_topic_ids:
        module_active = UserGrammarTopicStatus.query.filter(
            UserGrammarTopicStatus.user_id == user_id,
            UserGrammarTopicStatus.topic_id.in_(module_topic_ids),
            UserGrammarTopicStatus.status.in_(['theory_completed', 'practicing']),
        ).first()
        if module_active:
            topic = GrammarTopic.query.get(module_active.topic_id)
            if topic:
                grammar_topic = _build_grammar_dict(topic, module_active.status)
        else:
            # 2) Not-started topic from current module
            started_ids = {
                row[0] for row in db.session.query(UserGrammarTopicStatus.topic_id).filter(
                    UserGrammarTopicStatus.user_id == user_id,
                    UserGrammarTopicStatus.topic_id.in_(module_topic_ids),
                ).all()
            }
            for tid in module_topic_ids:
                if tid not in started_ids:
                    topic = GrammarTopic.query.get(tid)
                    if topic:
                        grammar_topic = _build_grammar_dict(topic, 'not_started')
                    break

    # 3) Fallback: any active topic ordered by GrammarTopic.order
    if not grammar_topic:
        fallback_status = UserGrammarTopicStatus.query.join(
            GrammarTopic, GrammarTopic.id == UserGrammarTopicStatus.topic_id,
        ).filter(
            UserGrammarTopicStatus.user_id == user_id,
            UserGrammarTopicStatus.status.in_(['theory_completed', 'practicing']),
        ).order_by(GrammarTopic.order).first()
        if fallback_status:
            topic = GrammarTopic.query.get(fallback_status.topic_id)
            if topic:
                grammar_topic = _build_grammar_dict(topic, fallback_status.status)

    # Words due for SRS review (capped by daily limits)
    # Count only eng-rus direction (1 card per word) — matches display semantics
    from app.study.models import StudySettings
    user_word_subq = db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
    raw_due = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.next_review <= now,
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    # Apply daily limits: count studied today in eng-rus only (consistent with raw_due)
    settings = StudySettings.get_settings(user_id)
    today_start_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)
    new_today = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(user_word_subq),
        UserCardDirection.direction == 'eng-rus',
        UserCardDirection.first_reviewed >= today_start_utc,
        UserCardDirection.first_reviewed.isnot(None),
    ).scalar() or 0
    reviews_today = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(user_word_subq),
        UserCardDirection.direction == 'eng-rus',
        UserCardDirection.last_reviewed >= today_start_utc,
        UserCardDirection.first_reviewed < today_start_utc,
        UserCardDirection.first_reviewed.isnot(None),
    ).scalar() or 0
    remaining_new = max(0, settings.new_words_per_day - new_today)
    remaining_reviews = max(0, settings.reviews_per_day - reviews_today)
    words_due = min(raw_due, remaining_new + remaining_reviews)

    # Book reading — find active book not read today
    today_start, today_end = _user_day_boundaries(tz)
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
            UserChapterProgress.updated_at < today_end,
        ).all()
        read_today_book_ids = {r[0] for r in read_today_book_ids}

        not_read_today = [bid for bid in started_book_ids if bid not in read_today_book_ids]
        if not_read_today:
            book = Book.query.get(not_read_today[0])
            if book:
                book_to_read = {'title': book.title, 'id': book.id}

    # Suggest books for users who haven't started any (non-onboarding)
    suggested_books = None
    if not started_book_ids and not book_to_read:
        suggestions = Book.query.filter(
            Book.chapters_cnt > 0,
        ).order_by(Book.level, Book.title).limit(3).all()
        if suggestions:
            suggested_books = [
                {'id': b.id, 'title': b.title}
                for b in suggestions
            ]

    # Onboarding: concrete suggestions for new users
    has_any_words = UserWord.query.filter_by(user_id=user_id).first() is not None
    has_any_lessons = LessonProgress.query.filter_by(user_id=user_id).first() is not None
    has_any_books = len(started_book_ids) > 0

    onboarding = None
    if not has_any_lessons and not has_any_books and not has_any_words:
        onboarding = {}

        # Suggest first lesson if user hasn't started the course
        if not has_any_lessons and not next_lesson:
            first_module = Module.query.order_by(Module.number).first()
            if first_module:
                first_lesson = Lessons.query.filter_by(
                    module_id=first_module.id,
                ).order_by(Lessons.order).first()
                if first_lesson:
                    level = first_module.level
                    # Find first grammar lesson title in the module
                    grammar_lesson = Lessons.query.filter_by(
                        module_id=first_module.id,
                        type='grammar',
                    ).order_by(Lessons.order).first()
                    grammar_topic_title = grammar_lesson.title if grammar_lesson else None
                    grammar_minutes = LESSON_TIME.get('grammar', 12)
                    onboarding['first_lesson'] = {
                        'title': first_lesson.title,
                        'module_title': first_module.title,
                        'level_name': level.name if level else None,
                        'level_code': level.code if level else None,
                        'module_number': first_module.number,
                        'grammar_topic_title': grammar_topic_title,
                        'estimated_minutes': grammar_minutes,
                    }

        # Suggest books if user hasn't started any (max 5)
        if not has_any_books:
            available_books = Book.query.filter(
                Book.chapters_cnt > 0,
            ).order_by(Book.level, Book.title).limit(5).all()
            total_books = Book.query.filter(Book.chapters_cnt > 0).count()
            if available_books:
                onboarding['available_books'] = [
                    {'id': b.id, 'title': b.title, 'author': b.author, 'level': b.level}
                    for b in available_books
                ]
                onboarding['total_books'] = total_books

        if not has_any_words:
            onboarding['no_words'] = True

    # Bonus task: extra lesson or extra reading
    bonus: dict[str, Any] = {}
    if next_lesson and next_lesson.get('lesson_id'):
        planned = Lessons.query.get(next_lesson['lesson_id'])
        if planned:
            extra = Lessons.query.filter(
                Lessons.module_id == planned.module_id,
                Lessons.order > planned.order,
            ).order_by(Lessons.order).first()
            if not extra:
                next_mod = Module.query.filter(
                    Module.number == (Module.query.get(planned.module_id).number + 1 if Module.query.get(planned.module_id) else 0),
                ).first()
                if next_mod:
                    extra = Lessons.query.filter(
                        Lessons.module_id == next_mod.id,
                    ).order_by(Lessons.order).first()
            if extra:
                bonus_completed_today = LessonProgress.query.filter(
                    LessonProgress.user_id == user_id,
                    LessonProgress.lesson_id == extra.id,
                    LessonProgress.status == 'completed',
                    LessonProgress.completed_at >= today_start,
                    LessonProgress.completed_at < today_end,
                ).first()
                if not bonus_completed_today:
                    extra_module = Module.query.get(extra.module_id)
                    bonus['extra_lesson'] = {
                        'title': extra.title,
                        'lesson_id': extra.id,
                        'module_number': extra_module.number if extra_module else None,
                        'lesson_type': extra.type,
                    }
    bonus['extra_reading'] = book_to_read is not None or bool(started_book_ids)

    return {
        'next_lesson': next_lesson,
        'grammar_topic': grammar_topic,
        'words_due': words_due,
        'has_any_words': has_any_words,
        'book_to_read': book_to_read,
        'suggested_books': suggested_books,
        'onboarding': onboarding,
        'bonus': bonus,
    }


def get_daily_summary(user_id: int, tz: str = DEFAULT_TZ) -> dict[str, Any]:
    """Get summary of today's activity in user's timezone."""
    today_start, today_end = _user_day_boundaries(tz)

    # Lessons completed today
    lessons_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        LessonProgress.completed_at >= today_start,
        LessonProgress.completed_at < today_end,
    ).all()

    lesson_types: list[str] = []
    for lp in lessons_completed:
        lesson = Lessons.query.get(lp.lesson_id)
        if lesson and lesson.type:
            lesson_types.append(lesson.type)

    # Grammar exercises done today
    grammar_done = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= today_start,
        UserGrammarExercise.last_reviewed < today_end,
    ).count()

    grammar_correct = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= today_start,
        UserGrammarExercise.last_reviewed < today_end,
    ).with_entities(
        func.sum(UserGrammarExercise.correct_count)
    ).scalar() or 0

    # Words reviewed today
    words_reviewed = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.last_reviewed < today_end,
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
        UserChapterProgress.updated_at < today_end,
    ).distinct().all()
    book_titles = [r[0] for r in books_read_today]

    return {
        'lessons_count': len(lesson_types),
        'lesson_types': lesson_types,
        'grammar_exercises': grammar_done,
        'grammar_correct': grammar_correct,
        'words_reviewed': words_reviewed,
        'books_read': book_titles,
    }


def get_weekly_report(user_id: int, tz: str = DEFAULT_TZ) -> dict[str, Any]:
    """Get weekly statistics for the report."""
    today_start, _ = _user_day_boundaries(tz)
    week_start = today_start - timedelta(days=7)
    prev_week_start = week_start - timedelta(days=7)
    now = today_start  # use start of today as "end of this week"

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

    streak = get_current_streak(user_id, tz=tz)

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


def get_quick_stats(user_id: int, tz: str = DEFAULT_TZ) -> dict[str, Any]:
    """Quick stats for /stats command."""
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

    streak = get_current_streak(user_id, tz=tz)

    # Books: progress per book (title, chapters read, total chapters, last read date)
    from app.books.models import Chapter
    books_data = db.session.query(
        Book.title,
        Book.chapters_cnt,
        func.max(Chapter.chap_num).label('max_chapter'),
        func.count(UserChapterProgress.chapter_id).label('chapters_read'),
        func.max(UserChapterProgress.updated_at).label('last_read'),
    ).join(
        Chapter, Chapter.book_id == Book.id
    ).join(
        UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id
    ).filter(
        UserChapterProgress.user_id == user_id,
    ).group_by(Book.id, Book.title, Book.chapters_cnt).all()

    books = []
    for row in books_data:
        total = row.chapters_cnt or row.max_chapter or 1
        pct = round(row.chapters_read / total * 100) if total else 0
        books.append({
            'title': row.title,
            'chapters_read': row.chapters_read,
            'chapters_total': total,
            'progress_pct': min(pct, 100),
            'last_read': row.last_read,
        })
    # Sort by last_read descending
    books.sort(key=lambda b: b['last_read'] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    return {
        'streak': streak,
        'lessons_completed': lessons_completed,
        'exercises_done': exercises_done,
        'words_in_srs': words_in_srs,
        'books': books,
    }


def get_tomorrow_preview(user_id: int) -> dict[str, Any] | None:
    """Get next lesson title for evening 'Завтра' line."""
    last_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
    ).order_by(LessonProgress.completed_at.desc()).first()

    if not last_completed:
        return None

    lesson = Lessons.query.get(last_completed.lesson_id)
    if not lesson:
        return None

    module = Module.query.get(lesson.module_id)
    if not module:
        return None

    # Find next lesson in same module or next module
    next_l = Lessons.query.filter(
        Lessons.module_id == module.id,
        Lessons.order > lesson.order,
    ).order_by(Lessons.order).first()

    if not next_l:
        next_module = Module.query.filter(
            Module.number == module.number + 1,
        ).first()
        if next_module:
            next_l = Lessons.query.filter(
                Lessons.module_id == next_module.id,
            ).order_by(Lessons.order).first()

    if not next_l:
        return None

    next_module = Module.query.get(next_l.module_id)
    return {
        'title': next_l.title,
        'module_number': next_module.number if next_module else None,
        'lesson_order': next_l.order,
        'lesson_type': next_l.type,
        'lesson_id': next_l.id,
    }


def get_quickest_action(user_id: int, tz: str = DEFAULT_TZ) -> dict[str, Any] | None:
    """Find fastest streak-saving action. Priority: words > grammar > lesson."""
    now = datetime.now(timezone.utc)

    # Words due for review
    words_due = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.next_review <= now,
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    if words_due > 0:
        count = min(words_due, 10)
        return {
            'type': 'words',
            'label': f'{count} карточек',
            'count': count,
            'minutes': max(count // 5, 2),
        }

    # Grammar exercises due
    due_exercises = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.next_review <= now,
    ).count()

    if due_exercises > 0:
        count = min(due_exercises, 5)
        return {
            'type': 'grammar',
            'label': f'{count} упражнений',
            'count': count,
            'minutes': count * 2,
        }

    # Next lesson
    last_completed = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
    ).order_by(LessonProgress.completed_at.desc()).first()

    if last_completed:
        lesson = Lessons.query.get(last_completed.lesson_id)
        if lesson:
            module = Module.query.get(lesson.module_id)
            if module:
                next_l = Lessons.query.filter(
                    Lessons.module_id == module.id,
                    Lessons.order > lesson.order,
                ).order_by(Lessons.order).first()
                if next_l:
                    return {
                        'type': 'lesson',
                        'label': next_l.title,
                        'count': 1,
                        'minutes': 10,
                    }

    return None


def get_cards_url(user_id: int, site_url: str) -> str:
    """Build cards URL using user's default deck if set."""
    from app.auth.models import User
    user = User.query.get(user_id)
    if user and user.default_study_deck_id:
        return f'{site_url}/study/cards/deck/{user.default_study_deck_id}'
    return f'{site_url}/study/cards'
