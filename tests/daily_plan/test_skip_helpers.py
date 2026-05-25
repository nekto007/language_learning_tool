"""Tests for legacy LessonSkip rows and curriculum slot behavior.

Covers:
- get_deferred_lesson_ids
- get_skips_used_today
- find_next_lesson_linear with exclude_lesson_ids
- build_curriculum_slot ignores legacy LessonSkip rows and skip fields
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.daily_plan.linear.slots.curriculum_slot import (
    build_curriculum_slot,
    get_deferred_lesson_ids,
    get_skips_used_today,
)
from app.daily_plan.models import LessonSkip
from app.utils.db import db as real_db


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_user(db_session) -> User:
    s = _uid()
    user = User(username=f'skiphelp_{s}', email=f'skiphelp_{s}@example.com', active=True)
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_level(db_session, order: int) -> CEFRLevel:
    code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name=f'Level {code}', description='desc', order=order)
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level: CEFRLevel, number: int) -> Module:
    module = Module(
        level_id=level.id,
        number=number,
        title=f'{level.code} M{number}',
        description='desc',
        raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session, module: Module, number: int) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'{module.title} L{number}',
        type='quiz',
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _skip(db_session, user_id: int, lesson_id: int, skipped_on: date) -> LessonSkip:
    skip = LessonSkip(
        user_id=user_id,
        lesson_id=lesson_id,
        skipped_on_date=skipped_on,
        defer_until_date=skipped_on + timedelta(days=1),
    )
    db_session.add(skip)
    db_session.commit()
    return skip


class TestGetDeferredLessonIds:
    def test_no_skips_returns_empty_set(self, db_session):
        user = _make_user(db_session)
        today = date.today()
        result = get_deferred_lesson_ids(user.id, today, real_db)
        assert result == set()

    def test_future_deferred_lesson_included(self, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level, 1)
        lesson = _make_lesson(db_session, module, 1)

        today = date.today()
        _skip(db_session, user.id, lesson.id, today)

        result = get_deferred_lesson_ids(user.id, today, real_db)
        assert lesson.id in result

    def test_past_deferred_lesson_not_included(self, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level, 1)
        lesson = _make_lesson(db_session, module, 1)

        yesterday = date.today() - timedelta(days=1)
        _skip(db_session, user.id, lesson.id, yesterday)

        today = date.today()
        result = get_deferred_lesson_ids(user.id, today, real_db)
        assert lesson.id not in result

    def test_only_own_user_lessons_returned(self, db_session):
        user_a = _make_user(db_session)
        user_b = _make_user(db_session)
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level, 1)
        lesson = _make_lesson(db_session, module, 1)

        today = date.today()
        _skip(db_session, user_b.id, lesson.id, today)

        result = get_deferred_lesson_ids(user_a.id, today, real_db)
        assert result == set()


class TestGetSkipsUsedToday:
    def test_no_skips_returns_zero(self, db_session):
        user = _make_user(db_session)
        assert get_skips_used_today(user.id, date.today(), real_db) == 0

    def test_counts_today_skips_only(self, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level, 1)
        lesson1 = _make_lesson(db_session, module, 1)
        lesson2 = _make_lesson(db_session, module, 2)

        today = date.today()
        yesterday = today - timedelta(days=1)
        _skip(db_session, user.id, lesson1.id, today)
        _skip(db_session, user.id, lesson2.id, yesterday)

        assert get_skips_used_today(user.id, today, real_db) == 1

    def test_multiple_skips_today_counted(self, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level, 1)
        lesson1 = _make_lesson(db_session, module, 1)
        lesson2 = _make_lesson(db_session, module, 2)

        today = date.today()
        _skip(db_session, user.id, lesson1.id, today)
        _skip(db_session, user.id, lesson2.id, today)

        assert get_skips_used_today(user.id, today, real_db) == 2


class TestFindNextLessonLinearExclude:
    def test_excluded_lesson_skipped(self, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level, 1)
        lesson1 = _make_lesson(db_session, module, 1)
        lesson2 = _make_lesson(db_session, module, 2)

        result = find_next_lesson_linear(user.id, real_db, exclude_lesson_ids={lesson1.id})
        assert result is not None
        assert result.id == lesson2.id

    def test_no_exclusions_returns_first(self, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level, 1)
        lesson1 = _make_lesson(db_session, module, 1)
        _make_lesson(db_session, module, 2)

        result = find_next_lesson_linear(user.id, real_db)
        assert result is not None
        assert result.id == lesson1.id

    def test_all_excluded_returns_none(self, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level, 1)
        lesson1 = _make_lesson(db_session, module, 1)

        result = find_next_lesson_linear(user.id, real_db, exclude_lesson_ids={lesson1.id})
        assert result is None


class TestBuildCurriculumSlotIgnoresLessonSkipRows:
    def _curriculum(self, db_session):
        user = _make_user(db_session)
        level = _make_level(db_session, order=1)
        module = _make_module(db_session, level, 1)
        lesson1 = _make_lesson(db_session, module, 1)
        lesson2 = _make_lesson(db_session, module, 2)
        return user, lesson1, lesson2

    def test_no_lesson_skip_data_on_curriculum_slot(self, db_session):
        user, lesson1, lesson2 = self._curriculum(db_session)
        slot = build_curriculum_slot(user.id, real_db)
        assert slot.data.get('lesson_id') == lesson1.id
        assert 'skip_allowed' not in slot.data
        assert 'skips_remaining' not in slot.data

    def test_deferred_lesson_no_longer_replaced_by_next(self, db_session):
        user, lesson1, lesson2 = self._curriculum(db_session)
        today = date.today()
        _skip(db_session, user.id, lesson1.id, today)
        slot = build_curriculum_slot(user.id, real_db)
        assert slot.data.get('lesson_id') == lesson1.id

    def test_no_skip_data_when_completed(self, db_session):
        user, lesson1, lesson2 = self._curriculum(db_session)
        # mark lesson1 completed so curriculum slot returns done_today = completed
        db_session.add(LessonProgress(
            user_id=user.id, lesson_id=lesson1.id, status='completed', score=100.0,
        ))
        db_session.commit()
        # simulate done_today via patching _curriculum_done_today
        with patch('app.daily_plan.linear.slots.curriculum_slot._curriculum_done_today', return_value=True):
            slot = build_curriculum_slot(user.id, real_db)
        assert 'skip_allowed' not in slot.data

    def test_pre_passed_deferred_lesson_kept(self, db_session):
        user, lesson1, lesson2 = self._curriculum(db_session)
        today = date.today()
        _skip(db_session, user.id, lesson1.id, today)
        slot = build_curriculum_slot(user.id, real_db, next_lesson=lesson1)
        assert slot.data.get('lesson_id') == lesson1.id
