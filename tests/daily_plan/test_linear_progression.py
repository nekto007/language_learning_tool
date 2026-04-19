"""Tests for the linear progression module.

Verifies that find_next_lesson_linear, get_user_level_progress, and
get_module_upcoming respect the user's onboarding level, skip completed
lessons, and traverse module/level boundaries correctly.
"""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.progression import (
    LevelProgress,
    find_next_lesson_linear,
    get_module_upcoming,
    get_user_level_progress,
)
from app.utils.db import db as real_db


def _unique_code() -> str:
    # CEFRLevel.code is VARCHAR(2); keep exactly 2 chars, uppercase.
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session, onboarding_level: str | None = None) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'linprog_{suffix}',
        email=f'linprog_{suffix}@example.com',
        active=True,
        onboarding_level=onboarding_level,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_level(db_session, code: str, order: int) -> CEFRLevel:
    level = CEFRLevel(
        code=code,
        name=f'Level {code}',
        description='desc',
        order=order,
    )
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


def _make_lesson(
    db_session,
    module: Module,
    number: int,
    lesson_type: str = 'quiz',
) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'{module.title} L{number}',
        type=lesson_type,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _complete(db_session, user: User, lesson: Lessons) -> None:
    db_session.add(LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=100.0,
    ))
    db_session.commit()


@pytest.fixture
def curriculum(db_session):
    """Build a small curriculum: A1 (orders 1), A2 (2), B1 (3) — each with
    2 modules, each module with 3 lessons.
    """
    # Use unique codes to avoid collisions with other tests since db_session
    # uses savepoint rollback but CEFRLevel.code is unique.
    levels = {}
    for name, order in [('A1', 1), ('A2', 2), ('B1', 3)]:
        levels[name] = _make_level(db_session, _unique_code(), order)

    data: dict[str, dict[int, list[Lessons]]] = {}
    for code, level in levels.items():
        data[code] = {}
        for mod_num in [1, 2]:
            module = _make_module(db_session, level, mod_num)
            lessons = [
                _make_lesson(db_session, module, lesson_num)
                for lesson_num in [1, 2, 3]
            ]
            data[code][mod_num] = lessons
    return {'levels': levels, 'data': data}


class TestFindNextLessonLinear:
    def test_cold_start_no_onboarding_returns_first_overall(self, db_session, curriculum):
        user = _make_user(db_session, onboarding_level=None)
        next_lesson = find_next_lesson_linear(user.id, real_db)
        assert next_lesson is not None
        # First lesson overall: A1 M1 L1
        first = curriculum['data']['A1'][1][0]
        assert next_lesson.id == first.id

    def test_b1_user_skips_a1_and_a2(self, db_session, curriculum):
        b1_code = curriculum['levels']['B1'].code
        user = _make_user(db_session, onboarding_level=b1_code)

        next_lesson = find_next_lesson_linear(user.id, real_db)
        assert next_lesson is not None
        expected = curriculum['data']['B1'][1][0]
        assert next_lesson.id == expected.id

    def test_skips_completed_lessons_within_module(self, db_session, curriculum):
        a1_code = curriculum['levels']['A1'].code
        user = _make_user(db_session, onboarding_level=a1_code)

        l1 = curriculum['data']['A1'][1][0]
        _complete(db_session, user, l1)

        next_lesson = find_next_lesson_linear(user.id, real_db)
        expected = curriculum['data']['A1'][1][1]
        assert next_lesson.id == expected.id

    def test_crosses_module_boundary(self, db_session, curriculum):
        a1_code = curriculum['levels']['A1'].code
        user = _make_user(db_session, onboarding_level=a1_code)

        # complete A1 M1 in full
        for lesson in curriculum['data']['A1'][1]:
            _complete(db_session, user, lesson)

        next_lesson = find_next_lesson_linear(user.id, real_db)
        expected = curriculum['data']['A1'][2][0]
        assert next_lesson.id == expected.id

    def test_crosses_level_boundary(self, db_session, curriculum):
        a1_code = curriculum['levels']['A1'].code
        user = _make_user(db_session, onboarding_level=a1_code)

        # Complete all of A1
        for mod_num in [1, 2]:
            for lesson in curriculum['data']['A1'][mod_num]:
                _complete(db_session, user, lesson)

        next_lesson = find_next_lesson_linear(user.id, real_db)
        expected = curriculum['data']['A2'][1][0]
        assert next_lesson.id == expected.id

    def test_returns_none_when_all_completed(self, db_session, curriculum):
        a1_code = curriculum['levels']['A1'].code
        user = _make_user(db_session, onboarding_level=a1_code)

        for code in ['A1', 'A2', 'B1']:
            for mod_num in [1, 2]:
                for lesson in curriculum['data'][code][mod_num]:
                    _complete(db_session, user, lesson)

        assert find_next_lesson_linear(user.id, real_db) is None

    def test_non_completed_progress_does_not_skip_lesson(self, db_session, curriculum):
        a1_code = curriculum['levels']['A1'].code
        user = _make_user(db_session, onboarding_level=a1_code)

        first = curriculum['data']['A1'][1][0]
        db_session.add(LessonProgress(
            user_id=user.id,
            lesson_id=first.id,
            status='in_progress',
            score=0.0,
        ))
        db_session.commit()

        next_lesson = find_next_lesson_linear(user.id, real_db)
        assert next_lesson.id == first.id


class TestGetUserLevelProgress:
    def test_fresh_user_zero_percent(self, db_session, curriculum):
        a1_code = curriculum['levels']['A1'].code
        user = _make_user(db_session, onboarding_level=a1_code)

        lp = get_user_level_progress(user.id, real_db)
        assert isinstance(lp, LevelProgress)
        assert lp.level == a1_code
        assert lp.percent == 0
        # A1 has 2 modules * 3 lessons = 6
        assert lp.lessons_remaining_in_level == 6
        assert lp.lessons_remaining_to_next_level == 6

    def test_partial_completion_percent(self, db_session, curriculum):
        a1_code = curriculum['levels']['A1'].code
        user = _make_user(db_session, onboarding_level=a1_code)

        # Complete 3 / 6 A1 lessons
        for lesson in curriculum['data']['A1'][1]:
            _complete(db_session, user, lesson)

        lp = get_user_level_progress(user.id, real_db)
        assert lp.level == a1_code
        assert lp.percent == 50
        assert lp.lessons_remaining_in_level == 3

    def test_level_advances_after_full_completion(self, db_session, curriculum):
        a1_code = curriculum['levels']['A1'].code
        a2_code = curriculum['levels']['A2'].code
        user = _make_user(db_session, onboarding_level=a1_code)

        for mod_num in [1, 2]:
            for lesson in curriculum['data']['A1'][mod_num]:
                _complete(db_session, user, lesson)

        lp = get_user_level_progress(user.id, real_db)
        assert lp.level == a2_code
        assert lp.percent == 0
        assert lp.lessons_remaining_in_level == 6

    def test_all_completed_reports_top_level_full(self, db_session, curriculum):
        a1_code = curriculum['levels']['A1'].code
        b1_code = curriculum['levels']['B1'].code
        user = _make_user(db_session, onboarding_level=a1_code)

        for code in ['A1', 'A2', 'B1']:
            for mod_num in [1, 2]:
                for lesson in curriculum['data'][code][mod_num]:
                    _complete(db_session, user, lesson)

        lp = get_user_level_progress(user.id, real_db)
        assert lp.level == b1_code
        assert lp.percent == 100
        assert lp.lessons_remaining_in_level == 0
        assert lp.lessons_remaining_to_next_level == 0


class TestGetModuleUpcoming:
    def test_returns_next_lessons_within_module(self, db_session, curriculum):
        user = _make_user(db_session)
        lessons = curriculum['data']['A1'][1]
        upcoming = get_module_upcoming(user.id, lessons[0], real_db, limit=3)
        assert [l.id for l in upcoming] == [lessons[1].id, lessons[2].id]

    def test_does_not_cross_module(self, db_session, curriculum):
        user = _make_user(db_session)
        last_in_m1 = curriculum['data']['A1'][1][-1]
        upcoming = get_module_upcoming(user.id, last_in_m1, real_db, limit=3)
        assert upcoming == []

    def test_skips_completed(self, db_session, curriculum):
        user = _make_user(db_session)
        lessons = curriculum['data']['A1'][1]
        _complete(db_session, user, lessons[1])
        upcoming = get_module_upcoming(user.id, lessons[0], real_db, limit=3)
        assert [l.id for l in upcoming] == [lessons[2].id]

    def test_limit_respected(self, db_session, curriculum):
        user = _make_user(db_session)
        lessons = curriculum['data']['A1'][1]
        upcoming = get_module_upcoming(user.id, lessons[0], real_db, limit=1)
        assert len(upcoming) == 1
        assert upcoming[0].id == lessons[1].id

    def test_empty_list_on_none_current(self, db_session):
        user = _make_user(db_session)
        assert get_module_upcoming(user.id, None, real_db, limit=3) == []
