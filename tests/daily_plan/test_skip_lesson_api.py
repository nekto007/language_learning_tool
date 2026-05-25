"""Tests for POST /api/daily-plan/skip-lesson."""
from __future__ import annotations

from datetime import date, timedelta

from app.curriculum.models import Lessons
from app.daily_plan.models import LessonSkip


def _make_lesson(db_session, module, number: int, title: str) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=title,
        type='quiz',
        order=number,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _make_two_lesson_spine(db_session, module) -> tuple[Lessons, Lessons]:
    return (
        _make_lesson(db_session, module, 1, 'First lesson'),
        _make_lesson(db_session, module, 2, 'Second lesson'),
    )


def test_skip_lesson_records_deferral_and_returns_next(
    authenticated_client, db_session, test_user, test_module,
):
    lesson1, lesson2 = _make_two_lesson_spine(db_session, test_module)

    response = authenticated_client.post(
        '/api/daily-plan/skip-lesson',
        json={'lesson_id': lesson1.id},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['skips_remaining'] == 0
    assert data['next_lesson_id'] == lesson2.id

    row = db_session.query(LessonSkip).filter_by(
        user_id=test_user.id,
        lesson_id=lesson1.id,
    ).one()
    assert row.skipped_on_date == date.today()
    assert row.defer_until_date == date.today() + timedelta(days=1)


def test_skip_lesson_rejects_non_current_lesson(
    authenticated_client, db_session, test_module,
):
    lesson1, lesson2 = _make_two_lesson_spine(db_session, test_module)

    response = authenticated_client.post(
        '/api/daily-plan/skip-lesson',
        json={'lesson_id': lesson2.id},
    )

    assert lesson1.id != lesson2.id
    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_lesson'


def test_skip_lesson_double_call_same_lesson_returns_already_deferred(
    authenticated_client, db_session, test_module,
):
    lesson1, _lesson2 = _make_two_lesson_spine(db_session, test_module)

    first = authenticated_client.post(
        '/api/daily-plan/skip-lesson',
        json={'lesson_id': lesson1.id},
    )
    second = authenticated_client.post(
        '/api/daily-plan/skip-lesson',
        json={'lesson_id': lesson1.id},
    )

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.get_json()['error'] == 'already_deferred'


def test_skip_lesson_quota_exhausted_for_next_current_lesson(
    authenticated_client, db_session, test_module,
):
    lesson1, lesson2 = _make_two_lesson_spine(db_session, test_module)

    first = authenticated_client.post(
        '/api/daily-plan/skip-lesson',
        json={'lesson_id': lesson1.id},
    )
    second = authenticated_client.post(
        '/api/daily-plan/skip-lesson',
        json={'lesson_id': lesson2.id},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.get_json()['error'] == 'skip_quota_exhausted'


def test_skip_lesson_requires_integer_lesson_id(authenticated_client):
    response = authenticated_client.post(
        '/api/daily-plan/skip-lesson',
        json={'lesson_id': '1'},
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'invalid_lesson'
