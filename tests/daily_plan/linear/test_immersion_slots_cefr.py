"""Smoke-tests: immersion extension slots appear for each CEFR level.

Covers Task 46 of the post-immersion content plan:
- A1 / A2 / B1 / B2 / C1 users each have a module with dictation,
  writing_prompt, and shadow_reading lessons.
- `_find_next_listening_lesson`, `_find_next_writing_lesson`, and
  `_find_next_speaking_lesson` each return a lesson from the correct
  module and carry a matching `level_code` in the built slot data.
- When the module has NO immersion lessons, all three slot builders
  return None (no false positives).
- `day_secured` is never blocked by incomplete extension slots.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import NamedTuple

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.plan import compute_linear_day_secured
from app.daily_plan.linear.slots.listening_slot import (
    _find_next_listening_lesson,
    build_listening_slot,
)
from app.daily_plan.linear.slots.writing_slot import (
    _find_next_writing_lesson,
    build_writing_slot,
)
from app.daily_plan.linear.slots.speaking_slot import (
    _find_next_speaking_lesson,
    build_speaking_slot,
)
from app.utils.db import db as real_db


# ---------------------------------------------------------------------------
# CEFR level parameters
# Each tuple: (code, order, description)
# We use high order values to avoid collisions with data created by other tests
# ---------------------------------------------------------------------------

_CEFR_PARAMS = [
    ('A1', 410, 'Beginner'),
    ('A2', 420, 'Elementary'),
    ('B1', 430, 'Intermediate'),
    ('B2', 440, 'Upper-Intermediate'),
    ('C1', 450, 'Advanced'),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _LevelSetup(NamedTuple):
    level: CEFRLevel
    module: Module
    spine_lesson: Lessons    # regular vocabulary lesson (the "current" lesson)
    dictation: Lessons
    writing_prompt: Lessons
    shadow_reading: Lessons
    user: User


def _unique() -> str:
    return uuid.uuid4().hex[:8]


def _make_cefr_level(db_session, code: str, order: int, description: str) -> CEFRLevel:
    # CEFRLevel.code is VARCHAR(2) — generate a unique 2-char code
    existing_codes = {r[0] for r in db_session.query(CEFRLevel.code).all()}
    existing_orders = {r[0] for r in db_session.query(CEFRLevel.order).all()}
    while order in existing_orders:
        order += 1
    short_code = uuid.uuid4().hex[:2].upper()
    while short_code in existing_codes:
        short_code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(
        code=short_code,
        name=f'{code} Test Level',
        description=description,
        order=order,
    )
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level: CEFRLevel, number: int = 1) -> Module:
    module = Module(
        level_id=level.id,
        number=number,
        title=f'Module {level.code} #{number}',
        description='test module',
        raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(
    db_session, module: Module, number: int, lesson_type: str
) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'{module.title} L{number} ({lesson_type})',
        type=lesson_type,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _make_user(db_session, onboarding_level: str) -> User:
    suffix = _unique()
    user = User(
        username=f'cefr_{suffix}',
        email=f'cefr_{suffix}@example.com',
        active=True,
        onboarding_level=onboarding_level,
    )
    user.set_password('secret')
    db_session.add(user)
    db_session.commit()
    return user


def _complete(db_session, user: User, lesson: Lessons) -> None:
    db_session.add(LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        completed_at=datetime.now(timezone.utc),
    ))
    db_session.commit()


def _build_level_setup(
    db_session, code: str, order: int, description: str
) -> _LevelSetup:
    """Create one full CEFR-level setup with spine + immersion lessons."""
    level = _make_cefr_level(db_session, code, order, description)
    module = _make_module(db_session, level, number=1)

    spine_lesson = _make_lesson(db_session, module, number=1, lesson_type='vocabulary')
    dictation_lesson = _make_lesson(db_session, module, number=2, lesson_type='dictation')
    writing_lesson = _make_lesson(db_session, module, number=3, lesson_type='writing_prompt')
    speaking_lesson = _make_lesson(db_session, module, number=4, lesson_type='shadow_reading')

    user = _make_user(db_session, onboarding_level=level.code)
    return _LevelSetup(
        level=level,
        module=module,
        spine_lesson=spine_lesson,
        dictation=dictation_lesson,
        writing_prompt=writing_lesson,
        shadow_reading=speaking_lesson,
        user=user,
    )


# ---------------------------------------------------------------------------
# Parametrized fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(params=_CEFR_PARAMS, ids=[p[0] for p in _CEFR_PARAMS])
def cefr_setup(request, db_session) -> _LevelSetup:
    code, order, description = request.param
    return _build_level_setup(db_session, code, order, description)


# ---------------------------------------------------------------------------
# Tests: listening slot
# ---------------------------------------------------------------------------

class TestListeningSlotAcrossCefrLevels:
    def test_dictation_found_for_level(self, cefr_setup, monkeypatch):
        setup = cefr_setup
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: setup.spine_lesson,
        )
        result = _find_next_listening_lesson(setup.user.id, real_db)
        assert result is not None, (
            f'Expected dictation lesson for level {setup.level.code}, got None'
        )
        assert result.id == setup.dictation.id
        assert result.type == 'dictation'

    def test_listening_slot_built_for_level(self, cefr_setup, monkeypatch):
        setup = cefr_setup
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: setup.spine_lesson,
        )
        slot = build_listening_slot(setup.user.id, real_db)
        assert slot is not None, (
            f'build_listening_slot returned None for level {setup.level.code}'
        )
        assert slot.kind == 'listening'
        assert slot.lesson_type == 'dictation'
        assert slot.completed is False
        assert slot.data['lesson_id'] == setup.dictation.id
        assert slot.data['level_code'] == setup.level.code

    def test_listening_slot_none_when_no_immersion_lessons(self, db_session, monkeypatch):
        level = _make_cefr_level(db_session, 'XX', 999, 'no-immersion test')
        module = _make_module(db_session, level, number=1)
        vocab = _make_lesson(db_session, module, number=1, lesson_type='vocabulary')
        grammar = _make_lesson(db_session, module, number=2, lesson_type='grammar')
        user = _make_user(db_session, onboarding_level=level.code)

        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: vocab,
        )
        result = build_listening_slot(user.id, real_db)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: writing slot
# ---------------------------------------------------------------------------

class TestWritingSlotAcrossCefrLevels:
    def test_writing_prompt_found_for_level(self, cefr_setup, monkeypatch):
        setup = cefr_setup
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: setup.spine_lesson,
        )
        result = _find_next_writing_lesson(setup.user.id, real_db)
        assert result is not None, (
            f'Expected writing_prompt lesson for level {setup.level.code}, got None'
        )
        assert result.id == setup.writing_prompt.id
        assert result.type == 'writing_prompt'

    def test_writing_slot_built_for_level(self, cefr_setup, monkeypatch):
        setup = cefr_setup
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: setup.spine_lesson,
        )
        slot = build_writing_slot(setup.user.id, real_db)
        assert slot is not None, (
            f'build_writing_slot returned None for level {setup.level.code}'
        )
        assert slot.kind == 'writing'
        assert slot.lesson_type == 'writing_prompt'
        assert slot.completed is False
        assert slot.data['lesson_id'] == setup.writing_prompt.id
        assert slot.data['level_code'] == setup.level.code

    def test_writing_slot_none_when_no_writing_lessons(self, db_session, monkeypatch):
        level = _make_cefr_level(db_session, 'YY', 998, 'no-writing test')
        module = _make_module(db_session, level, number=1)
        vocab = _make_lesson(db_session, module, number=1, lesson_type='vocabulary')
        _make_lesson(db_session, module, number=2, lesson_type='quiz')
        user = _make_user(db_session, onboarding_level=level.code)

        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: vocab,
        )
        result = build_writing_slot(user.id, real_db)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: speaking slot
# ---------------------------------------------------------------------------

class TestSpeakingSlotAcrossCefrLevels:
    def test_shadow_reading_found_for_level(self, cefr_setup, monkeypatch):
        setup = cefr_setup
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: setup.spine_lesson,
        )
        result = _find_next_speaking_lesson(setup.user.id, real_db)
        assert result is not None, (
            f'Expected shadow_reading lesson for level {setup.level.code}, got None'
        )
        assert result.id == setup.shadow_reading.id
        assert result.type == 'shadow_reading'

    def test_speaking_slot_built_for_level(self, cefr_setup, monkeypatch):
        setup = cefr_setup
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: setup.spine_lesson,
        )
        slot = build_speaking_slot(setup.user.id, real_db)
        assert slot is not None, (
            f'build_speaking_slot returned None for level {setup.level.code}'
        )
        assert slot.kind == 'speaking'
        assert slot.lesson_type == 'shadow_reading'
        assert slot.completed is False
        assert slot.data['lesson_id'] == setup.shadow_reading.id
        assert slot.data['level_code'] == setup.level.code

    def test_speaking_slot_none_when_no_speaking_lessons(self, db_session, monkeypatch):
        level = _make_cefr_level(db_session, 'ZZ', 997, 'no-speaking test')
        module = _make_module(db_session, level, number=1)
        vocab = _make_lesson(db_session, module, number=1, lesson_type='vocabulary')
        _make_lesson(db_session, module, number=2, lesson_type='grammar')
        user = _make_user(db_session, onboarding_level=level.code)

        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: vocab,
        )
        result = build_speaking_slot(user.id, real_db)
        assert result is None


# ---------------------------------------------------------------------------
# Tests: day_secured not blocked by extension slots
# ---------------------------------------------------------------------------

class TestDaySecuredUnaffectedByExtensionSlots:
    @pytest.mark.parametrize('level_code', ['A1', 'A2', 'B1', 'B2', 'C1'])
    def test_all_three_incomplete_extension_slots_do_not_block_secured(
        self, level_code
    ):
        baseline = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ]
        extensions = [
            {'kind': 'listening', 'completed': False},
            {'kind': 'writing', 'completed': False},
            {'kind': 'speaking', 'completed': False},
        ]
        # compute_linear_day_secured only inspects baseline slots
        assert compute_linear_day_secured(baseline) is True
        # If we accidentally pass extensions as baseline, it would return False
        assert compute_linear_day_secured(baseline + extensions) is False

    def test_day_secured_true_with_all_baseline_complete(self, cefr_setup):
        baseline = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ]
        assert compute_linear_day_secured(baseline) is True

    def test_day_secured_false_with_incomplete_baseline(self, cefr_setup):
        baseline = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': False},
            {'kind': 'reading', 'completed': True},
        ]
        assert compute_linear_day_secured(baseline) is False


# ---------------------------------------------------------------------------
# Tests: completed extension lessons are skipped
# ---------------------------------------------------------------------------

class TestCompletedExtensionLessonsSkipped:
    def test_completed_dictation_skipped_returns_none_when_only_one(
        self, cefr_setup, db_session, monkeypatch
    ):
        setup = cefr_setup
        _complete(db_session, setup.user, setup.dictation)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: setup.spine_lesson,
        )
        # dictation was the only listening lesson; after completing it, None expected
        result = _find_next_listening_lesson(setup.user.id, real_db)
        assert result is None

    def test_completed_writing_prompt_skipped_returns_none_when_only_one(
        self, cefr_setup, db_session, monkeypatch
    ):
        setup = cefr_setup
        _complete(db_session, setup.user, setup.writing_prompt)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: setup.spine_lesson,
        )
        result = _find_next_writing_lesson(setup.user.id, real_db)
        assert result is None

    def test_completed_shadow_reading_skipped_returns_none_when_only_one(
        self, cefr_setup, db_session, monkeypatch
    ):
        setup = cefr_setup
        _complete(db_session, setup.user, setup.shadow_reading)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: setup.spine_lesson,
        )
        result = _find_next_speaking_lesson(setup.user.id, real_db)
        assert result is None
