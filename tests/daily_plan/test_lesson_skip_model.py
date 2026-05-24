"""Tests for LessonSkip model: creation and unique constraint."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.models import LessonSkip


def _make_user(db_session) -> User:
    uid = uuid.uuid4().hex[:8]
    user = User(username=f'skip_{uid}', email=f'skip_{uid}@example.com', active=True)
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_lesson(db_session) -> Lessons:
    uid = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=uid, name='Beginner', description='desc', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='Module 1',
        description='desc',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title='Lesson 1',
        type='quiz',
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


class TestLessonSkipModel:
    def test_create_lesson_skip(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        today = date.today()
        tomorrow = today + timedelta(days=1)

        skip = LessonSkip(
            user_id=user.id,
            lesson_id=lesson.id,
            skipped_on_date=today,
            defer_until_date=tomorrow,
        )
        db_session.add(skip)
        db_session.commit()

        loaded = db_session.get(LessonSkip, skip.id)
        assert loaded is not None
        assert loaded.user_id == user.id
        assert loaded.lesson_id == lesson.id
        assert loaded.skipped_on_date == today
        assert loaded.defer_until_date == tomorrow
        assert loaded.created_at is not None

    def test_unique_constraint_same_user_lesson_date(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        today = date.today()
        tomorrow = today + timedelta(days=1)

        db_session.add(LessonSkip(
            user_id=user.id,
            lesson_id=lesson.id,
            skipped_on_date=today,
            defer_until_date=tomorrow,
        ))
        db_session.commit()

        db_session.add(LessonSkip(
            user_id=user.id,
            lesson_id=lesson.id,
            skipped_on_date=today,
            defer_until_date=tomorrow,
        ))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_same_lesson_different_date_allowed(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        today = date.today()
        yesterday = today - timedelta(days=1)

        db_session.add(LessonSkip(
            user_id=user.id,
            lesson_id=lesson.id,
            skipped_on_date=yesterday,
            defer_until_date=today,
        ))
        db_session.add(LessonSkip(
            user_id=user.id,
            lesson_id=lesson.id,
            skipped_on_date=today,
            defer_until_date=today + timedelta(days=1),
        ))
        db_session.commit()

        rows = db_session.query(LessonSkip).filter_by(user_id=user.id, lesson_id=lesson.id).all()
        assert len(rows) == 2

    def test_different_user_same_lesson_date_allowed(self, db_session):
        user_a = _make_user(db_session)
        user_b = _make_user(db_session)
        lesson = _make_lesson(db_session)
        today = date.today()
        tomorrow = today + timedelta(days=1)

        db_session.add(LessonSkip(
            user_id=user_a.id,
            lesson_id=lesson.id,
            skipped_on_date=today,
            defer_until_date=tomorrow,
        ))
        db_session.add(LessonSkip(
            user_id=user_b.id,
            lesson_id=lesson.id,
            skipped_on_date=today,
            defer_until_date=tomorrow,
        ))
        db_session.commit()

        count = db_session.query(LessonSkip).filter_by(lesson_id=lesson.id).count()
        assert count == 2

    def test_defer_until_date_one_day_after_skip(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        today = date.today()
        tomorrow = today + timedelta(days=1)

        skip = LessonSkip(
            user_id=user.id,
            lesson_id=lesson.id,
            skipped_on_date=today,
            defer_until_date=tomorrow,
        )
        db_session.add(skip)
        db_session.commit()

        loaded = db_session.get(LessonSkip, skip.id)
        assert (loaded.defer_until_date - loaded.skipped_on_date).days == 1
