"""Tests for DAU/WAU calculation via UNION 6 activity tables."""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonAttempt, LessonProgress, Lessons, Module
from app.utils.db import db


def _make_user(db_session):
    """Create a test user and flush to get an id."""
    username = f'u_{uuid.uuid4().hex[:8]}'
    user = User(
        username=username,
        email=f'{username}@test.com',
        active=True,
    )
    user.set_password('pass')
    db_session.add(user)
    db_session.flush()
    return user


def _make_lesson(db_session):
    """Create a minimal lesson hierarchy and return the Lessons object."""
    code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name='Test', description='Test', order=99)
    db_session.add(level)
    db_session.flush()

    module = Module(level_id=level.id, number=1, title='Test Module')
    db_session.add(module)
    db_session.flush()

    lesson = Lessons(module_id=module.id, number=1, title='Test Lesson', type='text', order=1)
    db_session.add(lesson)
    db_session.flush()
    return lesson


class TestCountActiveUsersInRange:
    """Verify _count_active_users_in_range counts correctly across all 6 tables."""

    @pytest.mark.smoke
    def test_study_session_counted(self, app, db_session):
        """User with StudySession in range is counted."""
        from app.admin.main_routes import _count_active_users_in_range
        from app.study.models import StudySession

        user = _make_user(db_session)
        now = datetime.now(timezone.utc)
        today = now.date()

        ss = StudySession(user_id=user.id, session_type='cards', start_time=now)
        db_session.add(ss)
        db_session.commit()

        count = _count_active_users_in_range(today, today)
        assert count >= 1

    def test_lesson_progress_counted(self, app, db_session):
        """User with LessonProgress activity in range is counted."""
        from app.admin.main_routes import _count_active_users_in_range

        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        now = datetime.now(timezone.utc)
        today = now.date()

        lp = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='completed',
            last_activity=now,
        )
        db_session.add(lp)
        db_session.commit()

        count = _count_active_users_in_range(today, today)
        assert count >= 1

    def test_lesson_attempt_counted(self, app, db_session):
        """User with LessonAttempt in range is counted."""
        from app.admin.main_routes import _count_active_users_in_range

        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        now = datetime.now(timezone.utc)
        today = now.date()

        attempt = LessonAttempt(
            user_id=user.id,
            lesson_id=lesson.id,
            attempt_number=1,
            started_at=now,
        )
        db_session.add(attempt)
        db_session.commit()

        count = _count_active_users_in_range(today, today)
        assert count >= 1

    def test_grammar_exercise_counted(self, app, db_session):
        """User with UserGrammarExercise reviewed in range is counted."""
        from app.admin.main_routes import _count_active_users_in_range
        from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise

        user = _make_user(db_session)
        now = datetime.now(timezone.utc)
        today = now.date()

        slug = f'test-topic-{uuid.uuid4().hex[:8]}'
        topic = GrammarTopic(
            slug=slug,
            title='Test Topic',
            title_ru='Тест',
            level='B1',
        )
        db_session.add(topic)
        db_session.flush()

        exercise = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'question': 'Test __.', 'correct_answer': 'answer'},
        )
        db_session.add(exercise)
        db_session.flush()

        uge = UserGrammarExercise(user_id=user.id, exercise_id=exercise.id)
        uge.last_reviewed = now
        db_session.add(uge)
        db_session.commit()

        count = _count_active_users_in_range(today, today)
        assert count >= 1

    def test_chapter_progress_counted(self, app, db_session):
        """User with UserChapterProgress updated in range is counted."""
        from app.admin.main_routes import _count_active_users_in_range
        from app.books.models import Book, Chapter, UserChapterProgress

        user = _make_user(db_session)
        now = datetime.now(timezone.utc)
        today = now.date()

        book = Book(
            title=f'Book {uuid.uuid4().hex[:8]}',
            author='Author',
            chapters_cnt=1,
            level='B1',
            unique_words=100,
        )
        db_session.add(book)
        db_session.flush()

        chapter = Chapter(
            book_id=book.id,
            chap_num=1,
            title='Chapter 1',
            words=500,
            text_raw='Some text here.',
        )
        db_session.add(chapter)
        db_session.flush()

        ucp = UserChapterProgress(
            user_id=user.id,
            chapter_id=chapter.id,
            offset_pct=0.5,
            updated_at=now,
        )
        db_session.add(ucp)
        db_session.commit()

        count = _count_active_users_in_range(today, today)
        assert count >= 1

    def test_book_course_enrollment_counted(self, app, db_session):
        """User with BookCourseEnrollment activity in range is counted."""
        from app.admin.main_routes import _count_active_users_in_range
        from app.books.models import Book
        from app.curriculum.book_courses import BookCourse, BookCourseEnrollment

        user = _make_user(db_session)
        now = datetime.now(timezone.utc)
        today = now.date()

        book = Book(
            title=f'Book {uuid.uuid4().hex[:8]}',
            author='Author',
            chapters_cnt=1,
            level='B1',
            unique_words=100,
        )
        db_session.add(book)
        db_session.flush()

        course = BookCourse(
            book_id=book.id,
            title='Test Course',
            level='B1',
            slug=f'test-course-{uuid.uuid4().hex[:8]}',
        )
        db_session.add(course)
        db_session.flush()

        enrollment = BookCourseEnrollment(
            user_id=user.id,
            course_id=course.id,
            last_activity=now,
        )
        db_session.add(enrollment)
        db_session.commit()

        count = _count_active_users_in_range(today, today)
        assert count >= 1

    def test_user_lesson_progress_counted(self, app, db_session):
        """User with UserLessonProgress.completed_at in range is counted (7th source)."""
        from app.admin.main_routes import _count_active_users_in_range, _active_user_ids_for_date
        from app.books.models import Book, Chapter
        from app.curriculum.book_courses import BookCourse, BookCourseModule, BookCourseEnrollment
        from app.curriculum.daily_lessons import DailyLesson, UserLessonProgress

        user = _make_user(db_session)
        now = datetime.now(timezone.utc)
        today = now.date()

        book = Book(
            title=f'Book {uuid.uuid4().hex[:8]}',
            author='Author',
            chapters_cnt=1,
            level='B1',
            unique_words=100,
        )
        db_session.add(book)
        db_session.flush()

        chapter = Chapter(
            book_id=book.id,
            chap_num=1,
            title='Chapter 1',
            words=500,
            text_raw='Some text here.',
        )
        db_session.add(chapter)
        db_session.flush()

        course = BookCourse(
            book_id=book.id,
            title='Course',
            level='B1',
            slug=f'course-{uuid.uuid4().hex[:8]}',
        )
        db_session.add(course)
        db_session.flush()

        module = BookCourseModule(
            course_id=course.id,
            module_number=1,
            title='Module 1',
        )
        db_session.add(module)
        db_session.flush()

        dl = DailyLesson(
            book_course_module_id=module.id,
            slice_number=1,
            day_number=1,
            lesson_type='reading',
            chapter_id=chapter.id,
            word_count=200,
        )
        db_session.add(dl)
        db_session.flush()

        enrollment = BookCourseEnrollment(
            user_id=user.id,
            course_id=course.id,
            status='active',
            current_module_id=module.id,
        )
        db_session.add(enrollment)
        db_session.flush()

        progress = UserLessonProgress(
            user_id=user.id,
            daily_lesson_id=dl.id,
            enrollment_id=enrollment.id,
            status='completed',
            completed_at=now,
        )
        # Explicitly null out enrollment.last_activity to isolate the source under test
        enrollment.last_activity = None
        db_session.add(progress)
        db_session.commit()

        count = _count_active_users_in_range(today, today)
        assert count >= 1

        ids = [row[0] for row in _active_user_ids_for_date(today).all()]
        assert user.id in ids

    def test_user_active_in_multiple_tables_counted_once(self, app, db_session):
        """User active in multiple tables is counted only once (UNION deduplication)."""
        from app.admin.main_routes import _count_active_users_in_range
        from app.study.models import StudySession

        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        now = datetime.now(timezone.utc)
        today = now.date()

        # Same user active in both study_sessions and lesson_progress
        ss = StudySession(user_id=user.id, session_type='cards', start_time=now)
        db_session.add(ss)

        lp = LessonProgress(
            user_id=user.id,
            lesson_id=lesson.id,
            status='completed',
            last_activity=now,
        )
        db_session.add(lp)

        # A second distinct user active only via lesson_attempts
        user2 = _make_user(db_session)
        attempt = LessonAttempt(
            user_id=user2.id,
            lesson_id=lesson.id,
            attempt_number=1,
            started_at=now,
        )
        db_session.add(attempt)
        db_session.commit()

        count = _count_active_users_in_range(today, today)
        # Must be exactly 2 (user + user2), not 3 — verifies UNION dedup
        assert count == 2

        # Confirm user1 is not double-counted by checking with only user1's records
        # We isolate by using a future date range where neither user has records
        tomorrow = today + timedelta(days=1)
        count_future = _count_active_users_in_range(tomorrow, tomorrow)
        assert count_future == 0

    def test_out_of_range_activity_not_counted(self, app, db_session):
        """Activity outside the date range is not counted."""
        from app.admin.main_routes import _count_active_users_in_range
        from app.study.models import StudySession

        user = _make_user(db_session)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        yesterday_date = yesterday.date()

        ss = StudySession(
            user_id=user.id,
            session_type='cards',
            start_time=yesterday,
        )
        db_session.add(ss)
        db_session.commit()

        # Query for a range that excludes yesterday
        far_future = date.today() + timedelta(days=10)
        count = _count_active_users_in_range(far_future, far_future)
        assert count == 0

    def test_empty_range_returns_zero(self, app, db_session):
        """Date range with no activity returns 0."""
        from app.admin.main_routes import _count_active_users_in_range

        far_past = date(2000, 1, 1)
        count = _count_active_users_in_range(far_past, far_past)
        assert count == 0
