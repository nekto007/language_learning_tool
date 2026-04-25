"""Tests for final-test attempt rate-limiting (Task 2)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.auth.models import User
from app.curriculum.grading import (
    FINAL_TEST_ATTEMPT_WINDOW_HOURS,
    FINAL_TEST_MAX_ATTEMPTS_PER_DAY,
    check_final_test_attempts_exhausted,
)
from app.curriculum.models import CEFRLevel, LessonAttempt, Lessons, Module


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session, *, is_admin: bool = False) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'final_user_{suffix}',
        email=f'final_user_{suffix}@example.com',
        active=True,
        is_admin=is_admin,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_final_test_lesson(db_session) -> Lessons:
    level = CEFRLevel(code=_unique_code(), name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='M1',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Final Test',
        type='final_test',
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _add_attempt(db_session, user_id: int, lesson_id: int, hours_ago: float, score: float = 50.0):
    started = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours_ago)
    attempt = LessonAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        attempt_number=1,
        started_at=started,
        completed_at=started,
        score=score,
        passed=score >= 70,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


def test_attempt_limit_allows_under_max(db_session):
    user = _make_user(db_session)
    lesson = _make_final_test_lesson(db_session)

    for _ in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY - 1):
        _add_attempt(db_session, user.id, lesson.id, hours_ago=1)

    assert check_final_test_attempts_exhausted(user.id, lesson.id, db_session=db_session) is None


def test_attempt_limit_blocks_at_max(db_session):
    user = _make_user(db_session)
    lesson = _make_final_test_lesson(db_session)

    for _ in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY):
        _add_attempt(db_session, user.id, lesson.id, hours_ago=1)

    result = check_final_test_attempts_exhausted(user.id, lesson.id, db_session=db_session)
    assert result is not None
    assert result['error'] == 'attempts_exhausted'
    assert result['passed'] is False
    assert result['max_attempts'] == FINAL_TEST_MAX_ATTEMPTS_PER_DAY
    assert result['window_hours'] == FINAL_TEST_ATTEMPT_WINDOW_HOURS
    assert 'retry_after' in result


def test_attempt_limit_window_expires(db_session):
    user = _make_user(db_session)
    lesson = _make_final_test_lesson(db_session)

    # All attempts older than the 24h window — should not block.
    for _ in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY + 1):
        _add_attempt(db_session, user.id, lesson.id, hours_ago=FINAL_TEST_ATTEMPT_WINDOW_HOURS + 1)

    assert check_final_test_attempts_exhausted(user.id, lesson.id, db_session=db_session) is None


def test_admin_user_bypasses_limit(db_session):
    user = _make_user(db_session, is_admin=True)
    lesson = _make_final_test_lesson(db_session)

    for _ in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY + 5):
        _add_attempt(db_session, user.id, lesson.id, hours_ago=1)

    assert check_final_test_attempts_exhausted(user.id, lesson.id, db_session=db_session) is None


def test_attempts_for_other_lesson_do_not_count(db_session):
    user = _make_user(db_session)
    lesson_a = _make_final_test_lesson(db_session)
    lesson_b = _make_final_test_lesson(db_session)

    for _ in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY):
        _add_attempt(db_session, user.id, lesson_a.id, hours_ago=1)

    assert check_final_test_attempts_exhausted(user.id, lesson_b.id, db_session=db_session) is None
