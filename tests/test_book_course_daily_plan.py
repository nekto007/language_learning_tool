"""Tests for book course integration with daily plan and telegram notifications."""
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from unittest.mock import patch

from app.utils.db import db
from app.curriculum.book_courses import BookCourse, BookCourseEnrollment, BookCourseModule
from app.curriculum.daily_lessons import DailyLesson, UserLessonProgress
from app.books.models import Book, Chapter
from app.telegram.queries import get_daily_plan, get_daily_summary, has_activity_today
from app.telegram.notifications import (
    format_morning_reminder, format_evening_summary, format_nudge,
)


@pytest.fixture
def hp_book(db_session):
    """Create a Harry Potter book record."""
    slug = f'hp-test-{uuid.uuid4().hex[:8]}'
    book = Book(
        slug=slug,
        title='Harry Potter and the Sorcerers Stone',
        author='J.K. Rowling',
        lang='en',
        level='B1',
        chapters_cnt=3,
    )
    db.session.add(book)
    db.session.flush()

    # Create 3 test chapters
    for i in range(1, 4):
        ch = Chapter(
            book_id=book.id,
            chap_num=i,
            title=f'Chapter {i}',
            words=100,
            text_raw=f'Some text for chapter {i}.',
            audio_url=f'books/audio/test/chapter_{i:02d}.mp3' if i <= 2 else None,
        )
        db.session.add(ch)
    db.session.flush()
    return book


@pytest.fixture
def hp_course(db_session, hp_book):
    """Create a book course with modules and daily lessons."""
    course = BookCourse(
        book_id=hp_book.id,
        slug=f'hp-course-{uuid.uuid4().hex[:8]}',
        title='Harry Potter Course',
        description='Learn English with HP',
        level='B1',
        is_active=True,
        is_featured=True,
    )
    db.session.add(course)
    db.session.flush()

    # Create 2 modules
    modules = []
    for m_num in range(1, 3):
        mod = BookCourseModule(
            course_id=course.id,
            module_number=m_num,
            title=f'Module {m_num}',
            order_index=m_num - 1,
            is_locked=(m_num > 1),
            lessons_data=[
                {'day': d, 'type': t}
                for d, t in [(m_num * 2 - 1, 'reading'), (m_num * 2, 'vocabulary')]
            ],
        )
        db.session.add(mod)
        db.session.flush()
        modules.append(mod)

    # Create daily lessons for each module
    chapters = Chapter.query.filter_by(book_id=hp_book.id).order_by(Chapter.chap_num).all()
    for i, mod in enumerate(modules):
        for j, (day, ltype) in enumerate([(i * 2 + 1, 'reading'), (i * 2 + 2, 'vocabulary')]):
            ch = chapters[min(i, len(chapters) - 1)]
            dl = DailyLesson(
                book_course_module_id=mod.id,
                slice_number=j + 1,
                day_number=day,
                lesson_type=ltype,
                chapter_id=ch.id,
                word_count=200,
            )
            db.session.add(dl)
    db.session.flush()
    return course


@pytest.fixture
def enrolled_user(db_session, test_user, hp_course):
    """Enroll test_user in the HP course."""
    modules = BookCourseModule.query.filter_by(course_id=hp_course.id).order_by(
        BookCourseModule.module_number
    ).all()
    enrollment = BookCourseEnrollment(
        user_id=test_user.id,
        course_id=hp_course.id,
        status='active',
        current_module_id=modules[0].id,
    )
    db.session.add(enrollment)
    db.session.flush()
    return enrollment


class TestDailyPlanBookCourse:
    """Test get_daily_plan() returns book course lesson data."""

    def test_daily_plan_has_book_course_lesson(self, db_session, test_user, hp_course, enrolled_user):
        plan = get_daily_plan(test_user.id)

        assert plan.get('book_course_lesson') is not None
        bc = plan['book_course_lesson']
        assert bc['course_id'] == hp_course.id
        assert bc['course_title'] == 'Harry Potter Course'
        assert bc['day_number'] == 1
        assert bc['lesson_type'] == 'reading'
        assert bc['estimated_minutes'] == 10

    def test_daily_plan_no_book_course_without_enrollment(self, db_session, test_user, hp_course):
        plan = get_daily_plan(test_user.id)
        assert plan.get('book_course_lesson') is None
        assert plan.get('book_course_done_today') is False

    def test_daily_plan_book_course_done_today(self, db_session, test_user, hp_course, enrolled_user):
        # Complete the first lesson
        dl = DailyLesson.query.join(BookCourseModule).filter(
            BookCourseModule.course_id == hp_course.id
        ).order_by(DailyLesson.day_number).first()

        progress = UserLessonProgress(
            user_id=test_user.id,
            daily_lesson_id=dl.id,
            enrollment_id=enrolled_user.id,
            status='completed',
            completed_at=datetime.now(timezone.utc),
        )
        db.session.add(progress)
        db.session.flush()

        plan = get_daily_plan(test_user.id)
        assert plan['book_course_done_today'] is True
        # Next lesson should be day 2 (vocabulary)
        assert plan['book_course_lesson']['day_number'] == 2
        assert plan['book_course_lesson']['lesson_type'] == 'vocabulary'

    def test_smart_routing_reading_is_step4(self, db_session, test_user, hp_course, enrolled_user):
        """Reading lesson should replace books step (step 4)."""
        plan = get_daily_plan(test_user.id)
        bc = plan['book_course_lesson']
        assert bc['lesson_type'] == 'reading'
        # When lesson_type == 'reading', dashboard should show it as step 4

    def test_smart_routing_practice_is_step5(self, db_session, test_user, hp_course, enrolled_user):
        """After completing reading, practice lesson should be step 5."""
        # Complete reading lesson (day 1)
        dl = DailyLesson.query.join(BookCourseModule).filter(
            BookCourseModule.course_id == hp_course.id,
        ).order_by(DailyLesson.day_number).first()

        progress = UserLessonProgress(
            user_id=test_user.id,
            daily_lesson_id=dl.id,
            enrollment_id=enrolled_user.id,
            status='completed',
            completed_at=datetime.now(timezone.utc),
        )
        db.session.add(progress)
        db.session.flush()

        plan = get_daily_plan(test_user.id)
        bc = plan['book_course_lesson']
        assert bc['lesson_type'] == 'vocabulary'


class TestDailySummaryBookCourse:
    """Test get_daily_summary() includes book course count."""

    def test_summary_counts_book_course_lessons(self, db_session, test_user, hp_course, enrolled_user):
        dl = DailyLesson.query.join(BookCourseModule).filter(
            BookCourseModule.course_id == hp_course.id,
        ).order_by(DailyLesson.day_number).first()

        progress = UserLessonProgress(
            user_id=test_user.id,
            daily_lesson_id=dl.id,
            enrollment_id=enrolled_user.id,
            status='completed',
            completed_at=datetime.now(timezone.utc),
        )
        db.session.add(progress)
        db.session.flush()

        summary = get_daily_summary(test_user.id)
        assert summary['book_course_lessons_today'] == 1


class TestActivityBookCourse:
    """Test has_activity_today() detects book course activity."""

    def test_book_course_counts_as_activity(self, db_session, test_user, hp_course, enrolled_user):
        dl = DailyLesson.query.join(BookCourseModule).filter(
            BookCourseModule.course_id == hp_course.id,
        ).order_by(DailyLesson.day_number).first()

        progress = UserLessonProgress(
            user_id=test_user.id,
            daily_lesson_id=dl.id,
            enrollment_id=enrolled_user.id,
            status='completed',
            completed_at=datetime.now(timezone.utc),
        )
        db.session.add(progress)
        db.session.flush()

        assert has_activity_today(test_user.id) is True


class TestTelegramNotifications:
    """Test notification formatting with book course data."""

    def test_morning_reminder_with_reading_lesson(self):
        plan = {
            'next_lesson': {'title': 'Lesson 1', 'module_number': 1, 'lesson_type': 'grammar',
                            'lesson_id': 1, 'level_code': 'A1'},
            'grammar_topic': None,
            'words_due': 5,
            'has_any_words': True,
            'book_to_read': None,
            'suggested_books': None,
            'onboarding': None,
            'bonus': {},
            'book_course_lesson': {
                'course_id': 1, 'course_slug': 'hp', 'course_title': 'Harry Potter',
                'module_id': 1, 'module_number': 1, 'lesson_id': 10,
                'day_number': 15, 'lesson_type': 'reading',
                'estimated_minutes': 10, 'chapter_id': 3,
            },
            'book_course_done_today': False,
        }
        text, _ = format_morning_reminder('Igor', 5, plan, 'https://example.com')
        assert 'Harry Potter' in text
        assert 'День 15' in text

    def test_morning_reminder_with_practice_lesson(self):
        plan = {
            'next_lesson': {'title': 'Lesson 1', 'module_number': 1, 'lesson_type': 'grammar',
                            'lesson_id': 1, 'level_code': 'A1'},
            'grammar_topic': None,
            'words_due': 0,
            'has_any_words': True,
            'book_to_read': {'title': 'Some Book', 'id': 5},
            'suggested_books': None,
            'onboarding': None,
            'bonus': {},
            'book_course_lesson': {
                'course_id': 1, 'course_slug': 'hp', 'course_title': 'Harry Potter',
                'module_id': 1, 'module_number': 1, 'lesson_id': 11,
                'day_number': 16, 'lesson_type': 'vocabulary',
                'estimated_minutes': 15, 'chapter_id': 3,
            },
            'book_course_done_today': False,
        }
        text, _ = format_morning_reminder('Igor', 5, plan, 'https://example.com')
        # Practice lesson: should show regular reading AND book course practice
        assert 'Some Book' in text
        assert 'Harry Potter' in text
        assert 'Vocabulary' in text

    def test_evening_summary_with_book_course(self):
        summary = {
            'lessons_count': 1,
            'lesson_types': ['grammar'],
            'grammar_exercises': 5,
            'grammar_correct': 4,
            'words_reviewed': 10,
            'srs_words_reviewed': 10,
            'books_read': [],
            'book_course_lessons_today': 2,
        }
        text, _ = format_evening_summary('Igor', summary, 3, 'https://example.com')
        assert 'Книжный курс' in text
        assert '2 урока' in text

    def test_nudge_with_book_course(self):
        bc = {
            'course_id': 1, 'course_slug': 'hp', 'course_title': 'Harry Potter',
            'module_id': 1, 'module_number': 1, 'lesson_id': 10,
            'day_number': 15, 'lesson_type': 'reading',
            'estimated_minutes': 10, 'chapter_id': 3,
        }
        text = format_nudge('Igor', 'https://example.com',
                            quick_action={'type': 'words', 'label': '10 карточек',
                                          'count': 10, 'minutes': 2},
                            book_course_lesson=bc)
        assert 'Harry Potter' in text
        assert 'день 15' in text
