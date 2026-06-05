"""Tests for app.curriculum.recovery (stuck-progress safety net)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.curriculum.models import (
    CEFRLevel,
    LessonAttempt,
    LessonProgress,
    Lessons,
    Module,
)
from app.curriculum.recovery import (
    _effective_passing_score,
    reconcile_stuck_lesson_progress,
)
from tests.conftest import unique_level_code


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'rec_{suffix}',
        email=f'rec_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_lesson(db_session, *, lesson_type='final_test', content=None) -> Lessons:
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
        title='L',
        type=lesson_type,
        content=content or {},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _make_progress(db_session, user, lesson, *, status='in_progress', score=0.0) -> LessonProgress:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    progress = LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status=status,
        score=score,
        started_at=now - timedelta(minutes=10),
        last_activity=now,
    )
    db_session.add(progress)
    db_session.commit()
    return progress


def _make_attempt(db_session, user, lesson, *, score=85.0, passed=True) -> LessonAttempt:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    attempt = LessonAttempt(
        user_id=user.id,
        lesson_id=lesson.id,
        attempt_number=1,
        started_at=now - timedelta(minutes=5),
        completed_at=now,
        score=score,
        passed=passed,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


class TestEffectivePassingScore:
    def test_dictation_default_is_80(self, db_session):
        lesson = _make_lesson(db_session, lesson_type='dictation', content={})
        assert _effective_passing_score(lesson) == 80

    def test_audio_fill_blank_default_is_80(self, db_session):
        lesson = _make_lesson(db_session, lesson_type='audio_fill_blank', content={})
        assert _effective_passing_score(lesson) == 80

    def test_other_default_is_70(self, db_session):
        lesson = _make_lesson(db_session, lesson_type='final_test', content={})
        assert _effective_passing_score(lesson) == 70

    def test_explicit_percent_wins(self, db_session):
        lesson = _make_lesson(
            db_session, lesson_type='final_test',
            content={'passing_score_percent': 85},
        )
        assert _effective_passing_score(lesson) == 85

    def test_legacy_key_fallback(self, db_session):
        lesson = _make_lesson(
            db_session, lesson_type='final_test',
            content={'passing_score': 75},
        )
        assert _effective_passing_score(lesson) == 75


class TestReconcile:
    def test_flips_when_attempt_passed(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        progress = _make_progress(db_session, user, lesson, score=50.0)
        _make_attempt(db_session, user, lesson, score=85.0, passed=True)

        report = reconcile_stuck_lesson_progress(db_session, dry_run=False)
        db_session.refresh(progress)

        assert report.flipped == 1
        assert report.flipped_by_attempt == 1
        assert progress.status == 'completed'
        assert progress.completed_at is not None
        assert progress.score == 85.0  # promoted to attempt's higher score

    def test_flips_when_score_meets_default_threshold(self, db_session):
        """Score 79 with default 70 threshold (final_test) → completed."""
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, content={})
        progress = _make_progress(db_session, user, lesson, score=79.0)

        report = reconcile_stuck_lesson_progress(db_session, dry_run=False)
        db_session.refresh(progress)

        assert report.flipped == 1
        assert report.flipped_by_score == 1
        assert progress.status == 'completed'

    def test_does_not_flip_when_score_below_explicit_threshold(self, db_session):
        """Score 79 with explicit content threshold 85 → stays in_progress."""
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, content={'passing_score_percent': 85})
        progress = _make_progress(db_session, user, lesson, score=79.0)

        report = reconcile_stuck_lesson_progress(db_session, dry_run=False)
        db_session.refresh(progress)

        assert report.flipped == 0
        assert progress.status == 'in_progress'

    def test_does_not_flip_already_completed(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        progress = _make_progress(db_session, user, lesson, status='completed', score=85.0)
        _make_attempt(db_session, user, lesson, score=85.0, passed=True)

        report = reconcile_stuck_lesson_progress(db_session, dry_run=False)
        db_session.refresh(progress)

        assert report.scanned == 0  # narrow query excludes status='completed'
        assert progress.status == 'completed'

    def test_dry_run_does_not_persist(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        progress = _make_progress(db_session, user, lesson, score=79.0)

        report = reconcile_stuck_lesson_progress(db_session, dry_run=True)
        db_session.expire(progress)

        assert report.flipped == 1
        assert progress.status == 'in_progress'  # rolled back

    def test_idempotent_second_run_no_op(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _make_progress(db_session, user, lesson, score=79.0)

        first = reconcile_stuck_lesson_progress(db_session, dry_run=False)
        second = reconcile_stuck_lesson_progress(db_session, dry_run=False)

        assert first.flipped == 1
        assert second.flipped == 0
        assert second.scanned == 0

    def test_does_not_regress_higher_existing_score(self, db_session):
        """Progress score 90 (somehow already higher than attempt) stays 90."""
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        progress = _make_progress(db_session, user, lesson, score=90.0)
        _make_attempt(db_session, user, lesson, score=75.0, passed=True)

        reconcile_stuck_lesson_progress(db_session, dry_run=False)
        db_session.refresh(progress)

        assert progress.status == 'completed'
        assert progress.score == 90.0
