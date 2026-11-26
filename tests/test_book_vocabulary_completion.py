from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from flask.testing import FlaskClient
from sqlalchemy.orm import Session

from app.auth.models import User
from app.books.models import Book, Chapter
from app.curriculum.book_courses import BookCourse, BookCourseEnrollment, BookCourseModule, BookModuleProgress
from app.curriculum.daily_lessons import DailyLesson, LessonCompletionEvent, UserLessonProgress
from app.curriculum.services.book_srs_integration import BookSRSIntegration


@dataclass
class VocabularyCourse:
    lesson: DailyLesson
    reading: DailyLesson
    enrollment: BookCourseEnrollment
    module_progress: BookModuleProgress


@pytest.fixture
def vocabulary_course(db_session: Session, test_user: User) -> VocabularyCourse:
    book = Book(title='Vocabulary receipt test', author='Fixture author', chapters_cnt=1)
    chapter = Chapter(book=book, chap_num=1, title='One', text_raw='A lamp lights the room.', words=6)
    course = BookCourse(book=book, title='Vocabulary receipt test', level='A2')
    module = BookCourseModule(course=course, module_number=1, title='First module')
    enrollment = BookCourseEnrollment(course=course, user=test_user)
    module_progress = BookModuleProgress(module=module, enrollment=enrollment)
    db_session.add_all([chapter, module_progress])
    db_session.flush()
    lesson = DailyLesson(module=module, chapter=chapter, day_number=1, slice_number=1, lesson_type='vocabulary')
    reading = DailyLesson(module=module, chapter=chapter, day_number=1, slice_number=2, lesson_type='reading')
    db_session.add_all([lesson, reading])
    db_session.commit()
    return VocabularyCourse(lesson, reading, enrollment, module_progress)


def test_vocabulary_retry_saves_once(
    authenticated_client: FlaskClient, vocabulary_course: VocabularyCourse, monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = vocabulary_course
    calls: list[tuple[int, int]] = []

    def create_cards(self: BookSRSIntegration, user_id: int, daily_lesson: DailyLesson) -> bool:
        calls.append((user_id, daily_lesson.id))
        return True

    monkeypatch.setattr(BookSRSIntegration, 'auto_create_srs_cards_from_vocabulary_lesson', create_cards)
    endpoint = f'/curriculum/api/v1/lesson/{course.lesson.id}/complete'
    first = authenticated_client.post(endpoint, json={})
    assert first.status_code == 201
    progress = UserLessonProgress.query.filter_by(daily_lesson_id=course.lesson.id).one()
    assert progress.status == 'completed'
    first_date = progress.completed_at
    assert first_date is not None

    retry = authenticated_client.post(endpoint, json={})
    assert (retry.status_code, retry.json) == (201, first.json)
    assert progress.completed_at == first_date
    assert LessonCompletionEvent.query.filter_by(daily_lesson_id=course.lesson.id).count() == 1
    assert course.module_progress.lessons_completed == [course.lesson.id]
    assert calls == [(course.enrollment.user_id, course.lesson.id)]

    # A neighbouring non-vocabulary v1 caller retains its existing behaviour.
    for _ in range(2):
        assert authenticated_client.post(
            f'/curriculum/api/v1/lesson/{course.reading.id}/complete', json={},
        ).status_code == 201
    assert LessonCompletionEvent.query.filter_by(daily_lesson_id=course.reading.id).count() == 2


@pytest.mark.parametrize('with_event', [False, True])
def test_legacy_completed_vocabulary_preserves_first_date_and_history(
    authenticated_client: FlaskClient, vocabulary_course: VocabularyCourse, db_session: Session, with_event: bool,
) -> None:
    course = vocabulary_course
    original_date = datetime(2024, 4, 10, 12, tzinfo=UTC)
    progress = UserLessonProgress(
        daily_lesson_id=course.lesson.id, user_id=course.enrollment.user_id, enrollment_id=course.enrollment.id,
        status='completed', completed_at=original_date, score=73, attempts=2,
    )
    db_session.add(progress)
    if with_event:
        db_session.add(LessonCompletionEvent(
            daily_lesson_id=course.lesson.id, user_id=course.enrollment.user_id, event_type='lesson_completed',
            created_at=original_date,
        ))
    db_session.commit()
    old_date = progress.completed_at
    old_module_list = course.module_progress.lessons_completed
    response = authenticated_client.post(f'/curriculum/api/v1/lesson/{course.lesson.id}/complete', json={})
    assert response.status_code == 201 and response.json['success']
    assert progress.completed_at == old_date
    assert (progress.score, progress.attempts) == (73, 2)
    assert course.module_progress.lessons_completed == old_module_list
    assert LessonCompletionEvent.query.filter_by(daily_lesson_id=course.lesson.id).count() == int(with_event)
