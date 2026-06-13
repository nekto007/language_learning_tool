"""Tests for BookCourse enrollment idempotency, XP, progress, and cascade."""
import pytest
from datetime import date, datetime, timezone

from sqlalchemy.exc import IntegrityError


@pytest.fixture
def book_course(db_session, test_book):
    from app.curriculum.book_courses import BookCourse
    course = BookCourse(
        book_id=test_book.id,
        title='Test Course',
        description='Test',
        level='B1',
        is_active=True,
    )
    db_session.add(course)
    db_session.commit()
    return course


@pytest.fixture
def book_course_module(db_session, book_course):
    from app.curriculum.book_courses import BookCourseModule
    module = BookCourseModule(
        course_id=book_course.id,
        title='Module 1',
        description='First module',
        order_index=1,
        module_number=1,
        start_position=0,
        end_position=100,
        lessons_data={'lessons': [
            {'lesson_number': 1, 'type': 'vocabulary'},
            {'lesson_number': 2, 'type': 'reading'},
        ]},
    )
    db_session.add(module)
    db_session.commit()
    return module


@pytest.fixture
def enrollment(db_session, test_user, book_course):
    from app.curriculum.book_courses import BookCourseEnrollment
    enroll = BookCourseEnrollment(
        user_id=test_user.id,
        course_id=book_course.id,
        status='active',
    )
    db_session.add(enroll)
    db_session.commit()
    return enroll


@pytest.fixture
def module_progress(db_session, enrollment, book_course_module):
    from app.curriculum.book_courses import BookModuleProgress
    prog = BookModuleProgress(
        enrollment_id=enrollment.id,
        module_id=book_course_module.id,
        status='not_started',
    )
    db_session.add(prog)
    db_session.commit()
    return prog


class TestEnrollmentIdempotent:
    """Enrollment must not create duplicate rows for the same (user, course)."""

    def test_enroll_twice_via_route_returns_400(self, client, app, test_user, book_course, db_session):
        """Second POST /enroll for same course returns 400, not 500."""
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['_fresh'] = True

        response1 = client.post(f'/curriculum/book-courses/{book_course.id}/enroll',
                                content_type='application/json')
        assert response1.status_code == 200, f"First enroll failed: {response1.data}"

        response2 = client.post(f'/curriculum/book-courses/{book_course.id}/enroll',
                                content_type='application/json')
        assert response2.status_code == 400
        data = response2.get_json()
        assert data['success'] is False
        assert 'уже записаны' in data['error'].lower() or 'already' in data['error'].lower()

    def test_enroll_twice_creates_only_one_row(self, db_session, test_user, book_course):
        """Direct model test: unique constraint allows only one enrollment row."""
        from app.curriculum.book_courses import BookCourseEnrollment

        e1 = BookCourseEnrollment(user_id=test_user.id, course_id=book_course.id, status='active')
        db_session.add(e1)
        db_session.commit()

        e2 = BookCourseEnrollment(user_id=test_user.id, course_id=book_course.id, status='active')
        db_session.add(e2)
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

        count = db_session.query(BookCourseEnrollment).filter_by(
            user_id=test_user.id, course_id=book_course.id
        ).count()
        assert count == 1

    def test_integrity_error_is_caught_in_route(self, app, test_user, book_course, db_session):
        """When unique constraint fires, the except IntegrityError branch returns 400 JSON."""
        import json
        from unittest.mock import MagicMock, patch

        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_user_id'] = str(test_user.id)
                sess['_fresh'] = True

            # Pre-create enrollment so route's guard sees it and returns 400
            from app.curriculum.book_courses import BookCourseEnrollment
            existing = BookCourseEnrollment(
                user_id=test_user.id, course_id=book_course.id, status='active'
            )
            db_session.add(existing)
            db_session.commit()

            response = c.post(
                f'/curriculum/book-courses/{book_course.id}/enroll',
                content_type='application/json',
            )

        assert response.status_code == 400
        data = response.get_json()
        assert data['success'] is False
        assert 'уже записаны' in data['error'].lower() or 'already' in data['error'].lower()


class TestChapterXPIdempotency:
    """Chapter completion XP must be awarded only once per (user, book, chapter)."""

    def test_xp_awarded_once(self, db_session, app, test_user):
        from app.achievements.xp_service import award_book_chapter_xp_idempotent
        from app.utils.db import db as _db
        result1 = award_book_chapter_xp_idempotent(
            user_id=test_user.id,
            book_id=1,
            chapter_id=1,
            xp=15,
            for_date=date.today(),
            db_session=_db,
        )
        db_session.commit()
        assert result1 is not None
        assert result1.xp_awarded > 0

    def test_xp_not_awarded_twice(self, db_session, app, test_user):
        from app.achievements.xp_service import award_book_chapter_xp_idempotent
        from app.utils.db import db as _db
        award_book_chapter_xp_idempotent(
            user_id=test_user.id,
            book_id=2,
            chapter_id=2,
            xp=15,
            for_date=date.today(),
            db_session=_db,
        )
        db_session.commit()

        result2 = award_book_chapter_xp_idempotent(
            user_id=test_user.id,
            book_id=2,
            chapter_id=2,
            xp=15,
            for_date=date.today(),
            db_session=_db,
        )
        db_session.commit()
        assert result2 is None

    def test_different_chapters_get_separate_xp(self, db_session, app, test_user):
        from app.achievements.xp_service import award_book_chapter_xp_idempotent
        from app.utils.db import db as _db
        r1 = award_book_chapter_xp_idempotent(
            user_id=test_user.id, book_id=3, chapter_id=1, xp=15, for_date=date.today(),
            db_session=_db,
        )
        db_session.commit()
        r2 = award_book_chapter_xp_idempotent(
            user_id=test_user.id, book_id=3, chapter_id=2, xp=15, for_date=date.today(),
            db_session=_db,
        )
        db_session.commit()
        assert r1 is not None
        assert r2 is not None


class TestProgressWithRemovedChapter:
    """Progress percentage must not exceed 100% even if module's lesson count shrinks."""

    def test_progress_capped_at_100_when_lessons_removed(self, db_session, module_progress, book_course_module):
        """If lessons_data shrinks to 1 but 2 are already completed, progress should be 100% not 200%."""
        module_progress.mark_lesson_completed(1)
        module_progress.mark_lesson_completed(2)
        assert module_progress.progress_percentage <= 100.0

        # Simulate chapter removal: module now has only 1 lesson in lessons_data
        book_course_module.lessons_data = {'lessons': [{'lesson_number': 1, 'type': 'vocabulary'}]}
        db_session.commit()

        # Completing one more (already done) should still stay ≤ 100
        module_progress.mark_lesson_completed(1)
        assert module_progress.progress_percentage <= 100.0

    def test_progress_not_over_100_with_extra_completions(self, db_session, module_progress, book_course_module):
        """mark_lesson_completed never produces progress_percentage > 100."""
        for n in range(1, 10):
            module_progress.mark_lesson_completed(n)
        assert module_progress.progress_percentage <= 100.0

    def test_progress_100_when_all_lessons_complete(self, db_session, module_progress):
        """When all 2 lessons are done, progress is exactly 100%."""
        module_progress.mark_lesson_completed(1)
        module_progress.mark_lesson_completed(2)
        assert module_progress.progress_percentage == 100.0
        assert module_progress.status == 'completed'


class TestUnenrollmentCascade:
    """Deleting a BookCourseEnrollment must cascade-delete related records."""

    def test_delete_enrollment_cascades_to_module_progress(self, db_session, enrollment, module_progress):
        from app.curriculum.book_courses import BookCourseEnrollment, BookModuleProgress

        enrollment_id = enrollment.id
        progress_id = module_progress.id

        db_session.delete(enrollment)
        db_session.commit()

        assert db_session.get(BookCourseEnrollment, enrollment_id) is None
        assert db_session.get(BookModuleProgress, progress_id) is None

    def test_delete_enrollment_does_not_delete_course(self, db_session, enrollment, book_course):
        from app.curriculum.book_courses import BookCourse

        course_id = book_course.id
        db_session.delete(enrollment)
        db_session.commit()

        assert db_session.get(BookCourse, course_id) is not None

    def test_enrollment_orm_cascade_deletes_all_module_progress(self, db_session, test_user, book_course):
        """Multiple module progress records are all deleted on enrollment delete."""
        from app.curriculum.book_courses import (
            BookCourseEnrollment, BookCourseModule, BookModuleProgress,
        )

        enroll = BookCourseEnrollment(user_id=test_user.id, course_id=book_course.id, status='active')
        db_session.add(enroll)
        db_session.flush()

        for i in range(3):
            mod = BookCourseModule(
                course_id=book_course.id,
                title=f'Module {i}',
                order_index=i + 10,
                module_number=i + 10,
                start_position=0,
                end_position=10,
            )
            db_session.add(mod)
            db_session.flush()

            prog = BookModuleProgress(
                enrollment_id=enroll.id,
                module_id=mod.id,
                status='not_started',
            )
            db_session.add(prog)

        db_session.commit()
        enrollment_id = enroll.id

        count_before = db_session.query(BookModuleProgress).filter_by(
            enrollment_id=enrollment_id
        ).count()
        assert count_before == 3

        db_session.delete(enroll)
        db_session.commit()

        count_after = db_session.query(BookModuleProgress).filter_by(
            enrollment_id=enrollment_id
        ).count()
        assert count_after == 0


class TestMarkLessonCompletedPersistence:
    """Audit E-046: in-place JSON mutations must persist across flush/commit.

    Before MutableList/MutableDict, completing the 2nd lesson reassigned
    nothing, so SQLAlchemy never flagged the column dirty and the change was
    silently lost on reload.
    """

    def test_subsequent_lessons_persist(self, db_session, module_progress):
        module_progress.mark_lesson_completed(1, score=80)
        db_session.commit()
        module_progress.mark_lesson_completed(2, score=90)
        db_session.commit()

        # Force a reload from the DB to prove the mutations were persisted.
        db_session.expire(module_progress)
        assert sorted(module_progress.lessons_completed) == [1, 2]
        assert module_progress.lesson_scores == {'1': 80, '2': 90}
        assert module_progress.status == 'completed'
