"""Tests for the canonical curriculum navigation.

Verify that `app.curriculum.navigation.find_next_lesson`, the linear daily
plan (`find_next_lesson_linear`), and the mission assembler
(`_find_next_lesson`) all return the same next-lesson identity for a
given user, and that checkpoint prerequisites on modules gate access.
"""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.curriculum.navigation import find_next_lesson
from app.daily_plan.assembler import _find_next_lesson as mission_find_next_lesson
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.utils.db import db as real_db


def _uniq_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session, onboarding_level: str | None = None) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'nav_{suffix}',
        email=f'nav_{suffix}@example.com',
        active=True,
        onboarding_level=onboarding_level,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_level(db_session, code: str, order: int) -> CEFRLevel:
    level = CEFRLevel(code=code, name=f'Level {code}', description='x', order=order)
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level: CEFRLevel, number: int, prerequisites=None) -> Module:
    module = Module(
        level_id=level.id,
        number=number,
        title=f'{level.code} M{number}',
        description='d',
        raw_content={},
        prerequisites=prerequisites,
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


def _complete(db_session, user: User, lesson: Lessons, score: float = 100.0) -> None:
    db_session.add(LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=score,
    ))
    db_session.commit()


@pytest.fixture
def mini_curriculum(db_session):
    level_a = _make_level(db_session, _uniq_code(), 1)
    level_b = _make_level(db_session, _uniq_code(), 2)

    a_m1 = _make_module(db_session, level_a, 1)
    a_m2 = _make_module(db_session, level_a, 2)
    b_m1 = _make_module(db_session, level_b, 1)

    a_m1_lessons = [_make_lesson(db_session, a_m1, n) for n in (1, 2)]
    a_m2_lessons = [_make_lesson(db_session, a_m2, n) for n in (1, 2)]
    b_m1_lessons = [_make_lesson(db_session, b_m1, n) for n in (1, 2)]

    return {
        'levels': (level_a, level_b),
        'modules': {'a1': a_m1, 'a2': a_m2, 'b1': b_m1},
        'lessons': {'a1': a_m1_lessons, 'a2': a_m2_lessons, 'b1': b_m1_lessons},
    }


class TestCanonicalConsistency:
    def test_all_surfaces_agree_on_next_lesson(self, db_session, mini_curriculum):
        user = _make_user(db_session)
        linear = find_next_lesson_linear(user.id, real_db)
        canonical = find_next_lesson(user.id, real_db)
        mission = mission_find_next_lesson(user_id=user.id)

        assert linear is not None
        assert canonical is not None and canonical.id == linear.id
        assert mission is not None and mission['lesson_id'] == linear.id

    def test_all_agree_after_partial_progress(self, db_session, mini_curriculum):
        user = _make_user(db_session)
        _complete(db_session, user, mini_curriculum['lessons']['a1'][0])

        linear = find_next_lesson_linear(user.id, real_db)
        canonical = find_next_lesson(user.id, real_db)
        mission = mission_find_next_lesson(user_id=user.id)

        assert linear.id == mini_curriculum['lessons']['a1'][1].id
        assert canonical.id == linear.id
        assert mission['lesson_id'] == linear.id

    def test_all_return_none_when_fully_completed(self, db_session, mini_curriculum):
        user = _make_user(db_session)
        for key in ('a1', 'a2', 'b1'):
            for lesson in mini_curriculum['lessons'][key]:
                _complete(db_session, user, lesson)

        assert find_next_lesson(user.id, real_db) is None
        assert mission_find_next_lesson(user_id=user.id) is None


class TestPrerequisiteGating:
    def test_locked_module_is_skipped(self, db_session, mini_curriculum):
        """If A2 requires ≥80% on A1 and the user only scored 50%, A2 must
        be skipped — find_next_lesson must not point at an A2 lesson."""
        user = _make_user(db_session)
        a_m1 = mini_curriculum['modules']['a1']
        a_m2 = mini_curriculum['modules']['a2']
        # Complete all A1 lessons with low score.
        for lesson in mini_curriculum['lessons']['a1']:
            _complete(db_session, user, lesson, score=50.0)
        # Gate A2 behind A1 ≥80%.
        a_m2.prerequisites = [{'type': 'module', 'id': a_m1.id, 'min_score': 80}]
        db_session.commit()

        canonical = find_next_lesson(user.id, real_db)
        # A1 is complete (all lessons done), A2 is locked → next must come
        # from the next eligible level/module (B1 M1 L1).
        assert canonical is not None
        assert canonical.id == mini_curriculum['lessons']['b1'][0].id

    def test_unlocked_module_is_reachable(self, db_session, mini_curriculum):
        user = _make_user(db_session)
        a_m1 = mini_curriculum['modules']['a1']
        a_m2 = mini_curriculum['modules']['a2']
        # Complete all A1 lessons with high score.
        for lesson in mini_curriculum['lessons']['a1']:
            _complete(db_session, user, lesson, score=100.0)
        a_m2.prerequisites = [{'type': 'module', 'id': a_m1.id, 'min_score': 80}]
        db_session.commit()

        canonical = find_next_lesson(user.id, real_db)
        assert canonical is not None
        assert canonical.id == mini_curriculum['lessons']['a2'][0].id
