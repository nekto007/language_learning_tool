"""Database queries for Telegram bot notifications."""
from datetime import datetime, timezone, timedelta, date
from typing import Any

import pytz
from sqlalchemy import func

from app.utils.db import db
from app.curriculum.models import LessonProgress, Lessons, Module
from app.curriculum.book_courses import BookCourse, BookCourseEnrollment, BookCourseModule
from app.curriculum.daily_lessons import DailyLesson, UserLessonProgress
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

    # Check book course lesson progress
    book_course_activity = UserLessonProgress.query.filter(
        UserLessonProgress.user_id == user_id,
        UserLessonProgress.completed_at >= today_start,
        UserLessonProgress.completed_at < today_end,
    ).first()
    if book_course_activity:
        return True

    return False


def _has_activity_in_range(user_id: int, start_utc: datetime,
                           end_utc: datetime) -> bool:
    """Check if user had any activity between start_utc and end_utc.

    Must check the same 5 sources as has_activity_today() to avoid
    streak gaps when user only did book reading or book course lessons.
    """
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

    # Book reading progress
    if UserChapterProgress.query.filter(
        UserChapterProgress.user_id == user_id,
        UserChapterProgress.updated_at >= start_utc,
        UserChapterProgress.updated_at < end_utc,
    ).first():
        return True

    # Book course lesson progress
    if UserLessonProgress.query.filter(
        UserLessonProgress.user_id == user_id,
        UserLessonProgress.completed_at >= start_utc,
        UserLessonProgress.completed_at < end_utc,
    ).first():
        return True

    return False


def get_current_streak(user_id: int, tz: str = DEFAULT_TZ) -> int:
    """Calculate current streak based on actual activity.

    Uses user's timezone to determine day boundaries.
    Pre-fetches repair events in one query to avoid N+1 problem.
    Repaired days (free_repair, spent_repair) always count toward the streak.
    Any real activity (checked via _has_activity_in_range) counts as a streak day.
    """
    from app.achievements.models import StreakEvent

    streak = 0

    if has_activity_today(user_id, tz=tz):
        streak = 1

    # Pre-fetch repair events for the last year in one query
    try:
        tz_obj = pytz.timezone(tz)
    except pytz.UnknownTimeZoneError:
        tz_obj = pytz.timezone(DEFAULT_TZ)
    local_now = datetime.now(tz_obj)
    earliest_date = local_now.date() - timedelta(days=366)

    repairs_by_date: dict[date, bool] = {}
    for ev in StreakEvent.query.filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type.in_(['free_repair', 'spent_repair']),
        StreakEvent.event_date >= earliest_date,
    ):
        repairs_by_date[ev.event_date] = True

    # Walk backwards through dates
    for offset in range(1, 366):
        check_date = local_now.date() - timedelta(days=offset)

        if check_date in repairs_by_date:
            streak += 1
            continue

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
                ).order_by(Lessons.number).first()

                if not next_l:
                    # Try next module
                    next_module = Module.query.filter(
                        Module.number == module.number + 1,
                    ).first()
                    if next_module:
                        next_l = Lessons.query.filter(
                            Lessons.module_id == next_module.id,
                        ).order_by(Lessons.number).first()

                if next_l:
                    next_module = Module.query.get(next_l.module_id)
                    level_code = None
                    if next_module and next_module.level:
                        level_code = next_module.level.code
                    # Module progress
                    module_total = Lessons.query.filter_by(module_id=next_l.module_id).count() if next_l.module_id else 0
                    module_completed = LessonProgress.query.filter(
                        LessonProgress.user_id == user_id,
                        LessonProgress.status == 'completed',
                        LessonProgress.lesson_id.in_(
                            db.session.query(Lessons.id).filter_by(module_id=next_l.module_id)
                        )
                    ).count() if next_l.module_id else 0

                    next_lesson = {
                        'title': next_l.title,
                        'module_number': next_module.number if next_module else None,
                        'lesson_order': next_l.order,
                        'lesson_type': next_l.type,
                        'lesson_id': next_l.id,
                        'level_code': level_code,
                        'module_lessons_total': module_total,
                        'module_lessons_completed': module_completed,
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
                ).order_by(Lessons.number).first()
                if first_lesson:
                    level = first_module.level
                    # Find first grammar lesson title in the module
                    grammar_lesson = Lessons.query.filter_by(
                        module_id=first_module.id,
                        type='grammar',
                    ).order_by(Lessons.number).first()
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

    # Book course: find next uncompleted lesson for active enrollment
    book_course_lesson = None
    book_course_done_today = False

    active_enrollment = BookCourseEnrollment.query.filter_by(
        user_id=user_id, status='active'
    ).first()

    if active_enrollment:
        # Check if any book course lesson was completed today
        bc_done = UserLessonProgress.query.filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.enrollment_id == active_enrollment.id,
            UserLessonProgress.completed_at >= today_start,
            UserLessonProgress.completed_at < today_end,
        ).first()
        book_course_done_today = bc_done is not None

        # Find next uncompleted daily lesson
        completed_lesson_ids = {
            r[0] for r in db.session.query(UserLessonProgress.daily_lesson_id).filter(
                UserLessonProgress.user_id == user_id,
                UserLessonProgress.enrollment_id == active_enrollment.id,
                UserLessonProgress.status == 'completed',
            ).all()
        }

        next_bc_lesson = DailyLesson.query.join(
            BookCourseModule, BookCourseModule.id == DailyLesson.book_course_module_id
        ).filter(
            BookCourseModule.course_id == active_enrollment.course_id,
        ).order_by(DailyLesson.day_number).all()

        for dl in next_bc_lesson:
            if dl.id not in completed_lesson_ids:
                module = BookCourseModule.query.get(dl.book_course_module_id)
                course = BookCourse.query.get(active_enrollment.course_id)
                book_course_lesson = {
                    'course_id': active_enrollment.course_id,
                    'course_slug': course.slug if course else None,
                    'course_title': course.title if course else None,
                    'module_id': module.id if module else None,
                    'module_number': module.module_number if module else None,
                    'lesson_id': dl.id,
                    'day_number': dl.day_number,
                    'lesson_type': dl.lesson_type,
                    'estimated_minutes': 10 if dl.lesson_type == 'reading' else 15,
                    'chapter_id': dl.chapter_id,
                }
                break

    # Bonus task: extra lesson or extra reading (max 1 bonus per day)
    bonus: dict[str, Any] = {}
    # Count curriculum lessons completed today (beyond the planned one)
    lessons_completed_today = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        LessonProgress.completed_at >= today_start,
        LessonProgress.completed_at < today_end,
    ).count()
    # Only show bonus if user hasn't already done 2+ lessons today (main + bonus)
    if lessons_completed_today < 2 and next_lesson and next_lesson.get('lesson_id'):
        planned = Lessons.query.get(next_lesson['lesson_id'])
        if planned:
            extra = Lessons.query.filter(
                Lessons.module_id == planned.module_id,
                Lessons.number > planned.number,
            ).order_by(Lessons.number).first()
            if not extra:
                planned_module = Module.query.get(planned.module_id)
                if planned_module:
                    next_mod = Module.query.filter(
                        Module.level_id == planned_module.level_id,
                        Module.number == planned_module.number + 1,
                    ).first()
                    if next_mod:
                        extra = Lessons.query.filter(
                            Lessons.module_id == next_mod.id,
                        ).order_by(Lessons.number).first()
            if extra:
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
        'words_new': remaining_new,
        'words_review': max(0, words_due - remaining_new),
        'has_any_words': has_any_words,
        'book_to_read': book_to_read,
        'suggested_books': suggested_books,
        'onboarding': onboarding,
        'bonus': bonus,
        'book_course_lesson': book_course_lesson,
        'book_course_done_today': book_course_done_today,
    }


def get_daily_plan_v2(user_id: int, tz: str = DEFAULT_TZ) -> dict[str, Any]:
    """Build daily study plan with per-step state machine.

    Each step has a 'state' field that determines how the UI renders it:
    - lesson: available / completed / suggest_start / all_done
    - grammar: available / completed / suggest_start
    - words: due / completed / all_reviewed / suggest_add
    - books: bc_reading / continue_book / completed / suggest_pick
    - book_course_practice: available / completed

    Steps with state=None are hidden from the plan.

    Also returns flat backward-compat keys for API/bot consumption.
    """
    now = datetime.now(timezone.utc)
    today_start, today_end = _user_day_boundaries(tz)

    # ── helpers ──
    from app.study.models import StudySettings
    from app.books.models import Chapter
    from sqlalchemy import distinct, case as sa_case

    CEFR_ORDER = sa_case(
        (Book.level == 'A1', 1), (Book.level == 'A2', 2),
        (Book.level == 'B1', 3), (Book.level == 'B2', 4),
        (Book.level == 'C1', 5), (Book.level == 'C2', 6),
        else_=7,
    )

    def _lesson_minutes_est(lesson_type: str | None) -> int:
        return LESSON_TIME.get(lesson_type or '', 10)

    def _words_minutes_est(count: int) -> int:
        return max(count // 8, 1) if count else 0

    # ──────────────────────────────────────────────
    # STEP 1: LESSON
    # ──────────────────────────────────────────────
    next_lesson = None
    lesson_step: dict[str, Any] | None = None

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
                ).order_by(Lessons.number).first()

                if not next_l:
                    next_module = Module.query.filter(
                        Module.number == module.number + 1,
                    ).first()
                    if next_module:
                        next_l = Lessons.query.filter(
                            Lessons.module_id == next_module.id,
                        ).order_by(Lessons.number).first()

                if next_l:
                    nl_module = Module.query.get(next_l.module_id)
                    level_code = nl_module.level.code if nl_module and nl_module.level else None
                    module_total = Lessons.query.filter_by(module_id=next_l.module_id).count()
                    module_completed = LessonProgress.query.filter(
                        LessonProgress.user_id == user_id,
                        LessonProgress.status == 'completed',
                        LessonProgress.lesson_id.in_(
                            db.session.query(Lessons.id).filter_by(module_id=next_l.module_id)
                        )
                    ).count()

                    next_lesson = {
                        'title': next_l.title,
                        'module_number': nl_module.number if nl_module else None,
                        'lesson_order': next_l.order,
                        'lesson_type': next_l.type,
                        'lesson_id': next_l.id,
                        'level_code': level_code,
                        'module_lessons_total': module_total,
                        'module_lessons_completed': module_completed,
                    }

    # Determine lesson step state
    has_any_lessons = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
    ).first() is not None
    lesson_done_today = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        LessonProgress.completed_at >= today_start,
        LessonProgress.completed_at < today_end,
    ).first() is not None

    if lesson_done_today:
        lesson_step = {
            'state': 'completed',
            **(next_lesson or {}),
            'estimated_minutes': _lesson_minutes_est(next_lesson.get('lesson_type')) if next_lesson else 10,
        }
    elif next_lesson:
        lesson_step = {
            'state': 'available',
            **next_lesson,
            'estimated_minutes': _lesson_minutes_est(next_lesson.get('lesson_type')),
        }
    elif has_any_lessons and not next_lesson:
        # All curriculum lessons completed
        lesson_step = {'state': 'all_done'}
    else:
        # No progress at all — suggest first lesson
        first_module = Module.query.order_by(Module.number).first()
        if first_module:
            first_lesson = Lessons.query.filter_by(
                module_id=first_module.id,
            ).order_by(Lessons.number).first()
            if first_lesson:
                level = first_module.level
                lesson_step = {
                    'state': 'suggest_start',
                    'title': first_lesson.title,
                    'lesson_id': first_lesson.id,
                    'module_number': first_module.number,
                    'lesson_type': first_lesson.type,
                    'level_code': level.code if level else None,
                    'first_module_title': first_module.title,
                    'estimated_minutes': _lesson_minutes_est(first_lesson.type),
                }

    # ──────────────────────────────────────────────
    # STEP 2: GRAMMAR
    # ──────────────────────────────────────────────
    grammar_topic = None
    grammar_step: dict[str, Any] | None = None

    current_module_id = None
    if next_lesson and next_lesson.get('lesson_id'):
        planned_lesson = Lessons.query.get(next_lesson['lesson_id'])
        if planned_lesson:
            current_module_id = planned_lesson.module_id

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

    # 3) Fallback: any active topic
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

    # Determine grammar step state
    grammar_done_today = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= today_start,
        UserGrammarExercise.last_reviewed < today_end,
    ).first() is not None

    if grammar_done_today:
        grammar_step = {
            'state': 'completed',
            **(grammar_topic or {}),
        }
    elif grammar_topic:
        grammar_step = {
            'state': 'available',
            **grammar_topic,
        }
    else:
        # No grammar activity and no topic found — suggest first topic
        first_topic = GrammarTopic.query.order_by(GrammarTopic.order).first()
        if first_topic:
            grammar_step = {
                'state': 'suggest_start',
                'title': first_topic.title,
                'topic_id': first_topic.id,
                'status': 'not_started',
                'due_exercises': 0,
                'first_topic_title': first_topic.title,
            }

    # ──────────────────────────────────────────────
    # STEP 3: WORDS (SRS)
    # ──────────────────────────────────────────────
    from app.auth.models import User as AuthUser
    from app.study.models import QuizDeckWord

    auth_user = AuthUser.query.get(user_id)
    default_deck_id = auth_user.default_study_deck_id if auth_user else None

    # Scope words to default deck if set, otherwise all user's words
    if default_deck_id:
        user_word_subq = (
            db.session.query(QuizDeckWord.user_word_id)
            .filter(
                QuizDeckWord.deck_id == default_deck_id,
                QuizDeckWord.user_word_id.isnot(None),
            )
        )
        has_any_words = db.session.query(user_word_subq.exists()).scalar()
    else:
        user_word_subq = db.session.query(UserWord.id).filter(UserWord.user_id == user_id)
        has_any_words = UserWord.query.filter_by(user_id=user_id).first() is not None

    raw_due = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(user_word_subq),
        UserCardDirection.next_review <= now,
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    # Apply daily limits using TZ-aware boundaries (Bug 1 fix)
    settings = StudySettings.get_settings(user_id)
    new_today = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(user_word_subq),
        UserCardDirection.direction == 'eng-rus',
        UserCardDirection.first_reviewed >= today_start,
        UserCardDirection.first_reviewed.isnot(None),
    ).scalar() or 0
    reviews_today = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(user_word_subq),
        UserCardDirection.direction == 'eng-rus',
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.first_reviewed < today_start,
        UserCardDirection.first_reviewed.isnot(None),
    ).scalar() or 0
    remaining_new = max(0, settings.new_words_per_day - new_today)
    remaining_reviews = max(0, settings.reviews_per_day - reviews_today)
    words_due = min(raw_due, remaining_new + remaining_reviews)

    # Words reviewed today (scoped to same deck)
    words_reviewed_today = db.session.query(func.count(UserCardDirection.id)).filter(
        UserCardDirection.user_word_id.in_(user_word_subq),
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.last_reviewed < today_end,
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    # Determine words step state
    words_step: dict[str, Any] | None = None
    if words_reviewed_today > 0 and words_due == 0:
        words_step = {
            'state': 'completed',
            'words_due': 0, 'words_new': 0, 'words_review': 0,
            'has_any_words': has_any_words,
            'estimated_minutes': 0,
        }
    elif words_due > 0:
        words_step = {
            'state': 'due',
            'words_due': words_due,
            'words_new': remaining_new,
            'words_review': max(0, words_due - remaining_new),
            'has_any_words': has_any_words,
            'estimated_minutes': _words_minutes_est(words_due),
        }
    elif has_any_words:
        # Has words but none due — auto-complete
        words_step = {
            'state': 'all_reviewed',
            'words_due': 0, 'words_new': 0, 'words_review': 0,
            'has_any_words': True,
            'estimated_minutes': 0,
        }
    else:
        # No words at all — suggest adding
        words_step = {
            'state': 'suggest_add',
            'words_due': 0, 'words_new': 0, 'words_review': 0,
            'has_any_words': False,
            'estimated_minutes': 0,
        }

    # ──────────────────────────────────────────────
    # STEP 4: BOOKS / READING
    # ──────────────────────────────────────────────
    book_to_read = None
    suggested_books = None
    books_step: dict[str, Any] | None = None

    started_book_ids = db.session.query(distinct(Chapter.book_id)).join(
        UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id
    ).filter(UserChapterProgress.user_id == user_id).all()
    started_book_ids = [r[0] for r in started_book_ids]

    books_read_today_ids: set[int] = set()
    if started_book_ids:
        books_read_today_ids = {
            r[0] for r in db.session.query(distinct(Chapter.book_id)).join(
                UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id
            ).filter(
                UserChapterProgress.user_id == user_id,
                UserChapterProgress.updated_at >= today_start,
                UserChapterProgress.updated_at < today_end,
            ).all()
        }

        not_read_today = [bid for bid in started_book_ids if bid not in books_read_today_ids]
        if not_read_today:
            book = Book.query.get(not_read_today[0])
            if book:
                book_to_read = {'title': book.title, 'id': book.id}
        elif started_book_ids:
            # All started books read today — fallback to first started (Bug 3 fix)
            book = Book.query.get(started_book_ids[0])
            if book:
                book_to_read = {'title': book.title, 'id': book.id}

    # Suggest books for users without started books
    if not started_book_ids:
        suggestions = Book.query.filter(
            Book.chapters_cnt > 0,
        ).order_by(CEFR_ORDER, Book.title).limit(3).all()
        if suggestions:
            suggested_books = [{'id': b.id, 'title': b.title} for b in suggestions]

    # Book course
    book_course_lesson = None
    book_course_done_today = False

    active_enrollment = BookCourseEnrollment.query.filter_by(
        user_id=user_id, status='active'
    ).first()

    if active_enrollment:
        bc_done = UserLessonProgress.query.filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.enrollment_id == active_enrollment.id,
            UserLessonProgress.completed_at >= today_start,
            UserLessonProgress.completed_at < today_end,
        ).first()
        book_course_done_today = bc_done is not None

        completed_lesson_ids = {
            r[0] for r in db.session.query(UserLessonProgress.daily_lesson_id).filter(
                UserLessonProgress.user_id == user_id,
                UserLessonProgress.enrollment_id == active_enrollment.id,
                UserLessonProgress.status == 'completed',
            ).all()
        }

        next_bc_lesson = DailyLesson.query.join(
            BookCourseModule, BookCourseModule.id == DailyLesson.book_course_module_id
        ).filter(
            BookCourseModule.course_id == active_enrollment.course_id,
        ).order_by(DailyLesson.day_number).all()

        for dl in next_bc_lesson:
            if dl.id not in completed_lesson_ids:
                bc_module = BookCourseModule.query.get(dl.book_course_module_id)
                course = BookCourse.query.get(active_enrollment.course_id)
                book_course_lesson = {
                    'course_id': active_enrollment.course_id,
                    'course_slug': course.slug if course else None,
                    'course_title': course.title if course else None,
                    'module_id': bc_module.id if bc_module else None,
                    'module_number': bc_module.module_number if bc_module else None,
                    'lesson_id': dl.id,
                    'day_number': dl.day_number,
                    'lesson_type': dl.lesson_type,
                    'estimated_minutes': 10 if dl.lesson_type == 'reading' else 15,
                    'chapter_id': dl.chapter_id,
                }
                break

    # Determine books step state
    bc_is_reading = book_course_lesson and book_course_lesson.get('lesson_type') == 'reading'
    bc_is_practice = book_course_lesson and book_course_lesson.get('lesson_type') != 'reading'

    if bc_is_reading:
        books_step = {
            'state': 'completed' if book_course_done_today else 'bc_reading',
            'book_course_lesson': book_course_lesson,
            'book_to_read': None,
            'suggested_books': None,
        }
    elif book_to_read:
        has_book_activity = bool(books_read_today_ids)
        books_step = {
            'state': 'completed' if has_book_activity else 'continue_book',
            'book_to_read': book_to_read,
            'book_course_lesson': None,
            'suggested_books': None,
        }
    else:
        # No books started — suggest picking
        books_step = {
            'state': 'suggest_pick',
            'book_to_read': None,
            'book_course_lesson': None,
            'suggested_books': suggested_books,
        }

    # ──────────────────────────────────────────────
    # STEP 5: BOOK COURSE PRACTICE
    # ──────────────────────────────────────────────
    bc_practice_step: dict[str, Any] | None = None

    if bc_is_practice:
        if book_course_done_today:
            bc_practice_step = {
                'state': 'completed',
                'lesson': book_course_lesson,
            }
        else:
            bc_practice_step = {
                'state': 'available',
                'lesson': book_course_lesson,
            }

    # ──────────────────────────────────────────────
    # BONUS (unchanged logic)
    # ──────────────────────────────────────────────
    bonus: dict[str, Any] = {}
    lessons_completed_today = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        LessonProgress.completed_at >= today_start,
        LessonProgress.completed_at < today_end,
    ).count()
    if lessons_completed_today < 2 and next_lesson and next_lesson.get('lesson_id'):
        planned = Lessons.query.get(next_lesson['lesson_id'])
        if planned:
            extra = Lessons.query.filter(
                Lessons.module_id == planned.module_id,
                Lessons.number > planned.number,
            ).order_by(Lessons.number).first()
            if not extra:
                planned_module = Module.query.get(planned.module_id)
                if planned_module:
                    next_mod = Module.query.filter(
                        Module.level_id == planned_module.level_id,
                        Module.number == planned_module.number + 1,
                    ).first()
                    if next_mod:
                        extra = Lessons.query.filter(
                            Lessons.module_id == next_mod.id,
                        ).order_by(Lessons.number).first()
            if extra:
                extra_module = Module.query.get(extra.module_id)
                bonus['extra_lesson'] = {
                    'title': extra.title,
                    'lesson_id': extra.id,
                    'module_number': extra_module.number if extra_module else None,
                    'lesson_type': extra.type,
                }
    bonus['extra_reading'] = book_to_read is not None or bool(started_book_ids)

    # ──────────────────────────────────────────────
    # BUILD RESULT
    # ──────────────────────────────────────────────
    # Add is_done flag to each step for template convenience
    _DONE_STATES = {'completed', 'all_reviewed', 'all_done'}
    for step in (lesson_step, grammar_step, words_step, books_step, bc_practice_step):
        if step is not None:
            step['is_done'] = step.get('state') in _DONE_STATES

    steps = {
        'lesson': lesson_step,
        'grammar': grammar_step,
        'words': words_step,
        'books': books_step,
        'book_course_practice': bc_practice_step,
    }

    # Backward-compat onboarding dict (deprecated, kept for bot)
    onboarding = None
    has_any_books = len(started_book_ids) > 0
    if not has_any_lessons and not has_any_books and not has_any_words:
        onboarding = {}
        if lesson_step and lesson_step.get('state') == 'suggest_start':
            first_module = Module.query.order_by(Module.number).first()
            if first_module:
                first_lesson_obj = Lessons.query.filter_by(
                    module_id=first_module.id,
                ).order_by(Lessons.number).first()
                if first_lesson_obj:
                    level = first_module.level
                    grammar_lesson = Lessons.query.filter_by(
                        module_id=first_module.id, type='grammar',
                    ).order_by(Lessons.number).first()
                    onboarding['first_lesson'] = {
                        'title': first_lesson_obj.title,
                        'module_title': first_module.title,
                        'level_name': level.name if level else None,
                        'level_code': level.code if level else None,
                        'module_number': first_module.number,
                        'grammar_topic_title': grammar_lesson.title if grammar_lesson else None,
                        'estimated_minutes': LESSON_TIME.get('grammar', 12),
                    }
        if not has_any_books:
            available_books = Book.query.filter(
                Book.chapters_cnt > 0,
            ).order_by(CEFR_ORDER, Book.title).limit(5).all()
            total_books = Book.query.filter(Book.chapters_cnt > 0).count()
            if available_books:
                onboarding['available_books'] = [
                    {'id': b.id, 'title': b.title, 'author': b.author, 'level': b.level}
                    for b in available_books
                ]
                onboarding['total_books'] = total_books
        if not has_any_words:
            onboarding['no_words'] = True

    return {
        # New per-step structure
        'steps': steps,

        # Backward-compat flat keys
        'next_lesson': next_lesson,
        'grammar_topic': grammar_topic,
        'words_due': words_due,
        'words_new': remaining_new,
        'words_review': max(0, words_due - remaining_new),
        'has_any_words': has_any_words,
        'book_to_read': book_to_read,
        'suggested_books': suggested_books,
        'onboarding': onboarding,
        'bonus': bonus,
        'book_course_lesson': book_course_lesson,
        'book_course_done_today': book_course_done_today,
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

    # Words reviewed today (all sources: curriculum lessons + SRS cards)
    words_reviewed = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.last_reviewed < today_end,
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    # Words reviewed in dedicated SRS card sessions only (excludes curriculum lessons)
    from app.study.models import StudySession
    srs_words_reviewed = db.session.query(
        func.coalesce(func.sum(StudySession.words_studied), 0)
    ).filter(
        StudySession.user_id == user_id,
        StudySession.session_type == 'cards',
        StudySession.start_time >= today_start,
        StudySession.start_time < today_end,
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

    # Book course lessons completed today
    book_course_lessons_today = UserLessonProgress.query.filter(
        UserLessonProgress.user_id == user_id,
        UserLessonProgress.status == 'completed',
        UserLessonProgress.completed_at >= today_start,
        UserLessonProgress.completed_at < today_end,
    ).count()

    # Extra details for dashboard step results
    latest_lesson_score = None
    latest_lesson_title = None
    if lessons_completed:
        last_lp = max(lessons_completed, key=lambda lp: lp.completed_at or datetime.min)
        latest_lesson_score = last_lp.score
        lesson_obj = Lessons.query.get(last_lp.lesson_id)
        if lesson_obj:
            latest_lesson_title = lesson_obj.title or ''

    # Grammar topic title (from today's exercises)
    grammar_topic_title = None
    if grammar_done > 0:
        latest_ge = UserGrammarExercise.query.filter(
            UserGrammarExercise.user_id == user_id,
            UserGrammarExercise.last_reviewed >= today_start,
            UserGrammarExercise.last_reviewed < today_end,
        ).order_by(UserGrammarExercise.last_reviewed.desc()).first()
        if latest_ge and latest_ge.exercise:
            from app.grammar_lab.models import GrammarTopic
            topic = GrammarTopic.query.get(latest_ge.exercise.topic_id)
            if topic:
                grammar_topic_title = topic.title

    # SRS breakdown: new vs review
    srs_new_reviewed = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.last_reviewed >= today_start,
        UserCardDirection.last_reviewed < today_end,
        UserCardDirection.direction == 'eng-rus',
        UserCardDirection.first_reviewed >= today_start,
    ).scalar() or 0
    srs_review_reviewed = max(0, words_reviewed - srs_new_reviewed)

    # Latest book chapter
    book_chapter_title = None
    if book_titles:
        latest_chapter = db.session.query(Chapter.title).join(
            UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id
        ).filter(
            UserChapterProgress.user_id == user_id,
            UserChapterProgress.updated_at >= today_start,
            UserChapterProgress.updated_at < today_end,
        ).order_by(UserChapterProgress.updated_at.desc()).first()
        if latest_chapter:
            book_chapter_title = latest_chapter[0]

    return {
        'lessons_count': len(lesson_types),
        'lesson_types': lesson_types,
        'grammar_exercises': grammar_done,
        'grammar_correct': grammar_correct,
        'words_reviewed': words_reviewed,
        'srs_words_reviewed': srs_words_reviewed,
        'srs_new_reviewed': srs_new_reviewed,
        'srs_review_reviewed': srs_review_reviewed,
        'books_read': book_titles,
        'book_course_lessons_today': book_course_lessons_today,
        'lesson_score': latest_lesson_score,
        'lesson_title': latest_lesson_title,
        'grammar_topic_title': grammar_topic_title,
        'book_chapter_title': book_chapter_title,
    }


def get_yesterday_summary(user_id: int, tz: str = DEFAULT_TZ) -> dict[str, Any]:
    """Get yesterday's activity summary (for dashboard badge)."""
    yesterday_start, yesterday_end = _user_day_boundaries(tz, offset_days=-1)

    lessons_count = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        LessonProgress.completed_at >= yesterday_start,
        LessonProgress.completed_at < yesterday_end,
    ).count()

    # Latest lesson score
    latest_lp = LessonProgress.query.filter(
        LessonProgress.user_id == user_id,
        LessonProgress.status == 'completed',
        LessonProgress.completed_at >= yesterday_start,
        LessonProgress.completed_at < yesterday_end,
    ).order_by(LessonProgress.completed_at.desc()).first()
    lesson_score = latest_lp.score if latest_lp else None

    words_reviewed = db.session.query(func.count(UserCardDirection.id)).join(UserWord).filter(
        UserWord.user_id == user_id,
        UserCardDirection.last_reviewed >= yesterday_start,
        UserCardDirection.last_reviewed < yesterday_end,
        UserCardDirection.direction == 'eng-rus',
    ).scalar() or 0

    grammar_done = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= yesterday_start,
        UserGrammarExercise.last_reviewed < yesterday_end,
    ).count()

    grammar_correct = UserGrammarExercise.query.filter(
        UserGrammarExercise.user_id == user_id,
        UserGrammarExercise.last_reviewed >= yesterday_start,
        UserGrammarExercise.last_reviewed < yesterday_end,
    ).with_entities(func.sum(UserGrammarExercise.correct_count)).scalar() or 0

    # Book reading and book course activity yesterday
    books_yesterday = UserChapterProgress.query.filter(
        UserChapterProgress.user_id == user_id,
        UserChapterProgress.updated_at >= yesterday_start,
        UserChapterProgress.updated_at < yesterday_end,
    ).first() is not None

    bc_yesterday = UserLessonProgress.query.filter(
        UserLessonProgress.user_id == user_id,
        UserLessonProgress.completed_at >= yesterday_start,
        UserLessonProgress.completed_at < yesterday_end,
    ).first() is not None

    has_any = (lessons_count > 0 or words_reviewed > 0 or grammar_done > 0
               or books_yesterday or bc_yesterday)
    return {
        'has_activity': has_any,
        'lessons_count': lessons_count,
        'lesson_score': lesson_score,
        'words_reviewed': words_reviewed,
        'grammar_exercises': grammar_done,
        'grammar_correct': grammar_correct,
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
    ).order_by(Lessons.number).first()

    if not next_l:
        next_module = Module.query.filter(
            Module.number == module.number + 1,
        ).first()
        if next_module:
            next_l = Lessons.query.filter(
                Lessons.module_id == next_module.id,
            ).order_by(Lessons.number).first()

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
                ).order_by(Lessons.number).first()
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
