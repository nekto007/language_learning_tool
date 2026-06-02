"""Tests for final-test attempt rate-limiting."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.curriculum.grading import (
    FINAL_TEST_ATTEMPT_WINDOW_HOURS,
    FINAL_TEST_MAX_ATTEMPTS_PER_DAY,
    check_final_test_attempts_exhausted,
)
from app.curriculum.models import CEFRLevel, LessonAttempt, Lessons, Module
from tests.conftest import unique_level_code


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
    level = CEFRLevel(code=unique_level_code(), name='L', description='d', order=1)
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


def test_passed_attempts_do_not_count_toward_limit(db_session):
    """Plan: 'не более 3 провалов за 24h' — passes don't consume retries."""
    user = _make_user(db_session)
    lesson = _make_final_test_lesson(db_session)

    for _ in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY + 2):
        _add_attempt(db_session, user.id, lesson.id, hours_ago=1, score=85.0)

    assert check_final_test_attempts_exhausted(user.id, lesson.id, db_session=db_session) is None


def test_attempts_for_other_lesson_do_not_count(db_session):
    user = _make_user(db_session)
    lesson_a = _make_final_test_lesson(db_session)
    lesson_b = _make_final_test_lesson(db_session)

    for _ in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY):
        _add_attempt(db_session, user.id, lesson_a.id, hours_ago=1)

    assert check_final_test_attempts_exhausted(user.id, lesson_b.id, db_session=db_session) is None


def test_retry_after_is_valid_iso_timestamp(db_session):
    """retry_after must be a parseable ISO-8601 timestamp string."""
    user = _make_user(db_session)
    lesson = _make_final_test_lesson(db_session)

    for _ in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY):
        _add_attempt(db_session, user.id, lesson.id, hours_ago=1)

    result = check_final_test_attempts_exhausted(user.id, lesson.id, db_session=db_session)
    assert result is not None
    retry_after_str = result['retry_after']
    # Must parse without error; raises ValueError on invalid format.
    parsed = datetime.fromisoformat(retry_after_str)
    assert parsed > datetime.now(timezone.utc)


def test_retry_after_is_24h_after_oldest_failed_attempt(db_session):
    """retry_after should be ~24h after the oldest failed attempt in the window."""
    user = _make_user(db_session)
    lesson = _make_final_test_lesson(db_session)

    oldest_hours_ago = 5.0
    _add_attempt(db_session, user.id, lesson.id, hours_ago=oldest_hours_ago)
    _add_attempt(db_session, user.id, lesson.id, hours_ago=2.0)
    _add_attempt(db_session, user.id, lesson.id, hours_ago=1.0)

    result = check_final_test_attempts_exhausted(user.id, lesson.id, db_session=db_session)
    assert result is not None

    retry_after = datetime.fromisoformat(result['retry_after'])
    expected = datetime.now(timezone.utc) - timedelta(hours=oldest_hours_ago) + timedelta(hours=FINAL_TEST_ATTEMPT_WINDOW_HOURS)
    # Allow 10-second tolerance for test execution time.
    assert abs((retry_after - expected).total_seconds()) < 10


def test_null_passed_attempts_do_not_count_toward_limit(db_session):
    """Attempts with passed=NULL (incomplete/errored) must not consume retries."""
    user = _make_user(db_session)
    lesson = _make_final_test_lesson(db_session)

    # Create attempts with passed=None (simulates crashed/interrupted attempts)
    for i in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY + 1):
        started = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        attempt = LessonAttempt(
            user_id=user.id,
            lesson_id=lesson.id,
            attempt_number=i + 1,
            started_at=started,
            completed_at=started,
            score=None,
            passed=None,
        )
        db_session.add(attempt)
    db_session.commit()

    # NULL passed attempts should not block the user
    assert check_final_test_attempts_exhausted(user.id, lesson.id, db_session=db_session) is None


@pytest.mark.smoke
def test_exhausted_check_does_not_create_lesson_attempt(db_session):
    """check_final_test_attempts_exhausted must never write LessonAttempt rows."""
    user = _make_user(db_session)
    lesson = _make_final_test_lesson(db_session)

    for _ in range(FINAL_TEST_MAX_ATTEMPTS_PER_DAY):
        _add_attempt(db_session, user.id, lesson.id, hours_ago=1)

    count_before = (
        db_session.query(LessonAttempt)
        .filter_by(user_id=user.id, lesson_id=lesson.id)
        .count()
    )

    result = check_final_test_attempts_exhausted(user.id, lesson.id, db_session=db_session)
    assert result is not None  # limit reached
    assert result['error'] == 'attempts_exhausted'

    count_after = (
        db_session.query(LessonAttempt)
        .filter_by(user_id=user.id, lesson_id=lesson.id)
        .count()
    )
    assert count_after == count_before, (
        "check_final_test_attempts_exhausted must not create any LessonAttempt rows"
    )
