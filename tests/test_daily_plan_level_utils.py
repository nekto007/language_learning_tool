"""Tests for app/daily_plan/level_utils.py"""
import uuid

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.level_utils import _cefr_code_to_order, get_user_current_cefr_level
from app.utils.db import db


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_level(db_session, code: str, order: int) -> CEFRLevel:
    level = CEFRLevel(code=code, name=code, order=order)
    db_session.add(level)
    db_session.flush()
    return level


def _make_module(db_session, level: CEFRLevel) -> Module:
    module = Module(
        level_id=level.id,
        number=uuid.uuid4().int % 10000,
        title=f"Module {uuid.uuid4().hex[:4]}",
        min_score_required=70,
        allow_skip_test=False,
        input_mode="mixed",
    )
    db_session.add(module)
    db_session.flush()
    return module


def _make_lesson(db_session, module: Module) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=uuid.uuid4().int % 10000,
        title=f"Lesson {uuid.uuid4().hex[:4]}",
        type="vocabulary",
        order=0,
        content={},
    )
    db_session.add(lesson)
    db_session.flush()
    return lesson


def _make_user(db_session, onboarding_level: str | None = None) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"testuser_{suffix}",
        email=f"testuser_{suffix}@example.com",
        active=True,
        onboarding_completed=True,
        onboarding_level=onboarding_level,
    )
    user.set_password("pass")
    db_session.add(user)
    db_session.flush()
    return user


def _complete_lesson(db_session, user: User, lesson: Lessons) -> LessonProgress:
    lp = LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status="completed",
        score=90.0,
    )
    db_session.add(lp)
    db_session.flush()
    return lp


# ---------------------------------------------------------------------------
# Tests for _cefr_code_to_order
# ---------------------------------------------------------------------------


def test_cefr_code_to_order_known_code(app, db_session):
    level = _make_level(db_session, code="ZZ", order=99)
    result = _cefr_code_to_order("ZZ", db)
    assert result == 99


def test_cefr_code_to_order_unknown_code(app, db_session):
    result = _cefr_code_to_order("XX", db)
    assert result == -1


def test_cefr_code_to_order_empty_string(app, db_session):
    result = _cefr_code_to_order("", db)
    assert result == -1


def test_cefr_code_to_order_none(app, db_session):
    result = _cefr_code_to_order(None, db)  # type: ignore[arg-type]
    assert result == -1


# ---------------------------------------------------------------------------
# Tests for get_user_current_cefr_level
# ---------------------------------------------------------------------------


def test_new_user_no_progress_no_onboarding_returns_a0(app, db_session):
    """User with no progress and no onboarding_level → 'A0'."""
    user = _make_user(db_session, onboarding_level=None)
    result = get_user_current_cefr_level(user.id, db)
    assert result == "A0"


def test_onboarding_b1_no_progress_returns_b1(app, db_session):
    """User with onboarding B1 and no completed lessons → 'B1'."""
    _make_level(db_session, code="B1", order=4)
    user = _make_user(db_session, onboarding_level="B1")
    result = get_user_current_cefr_level(user.id, db)
    assert result == "B1"


def test_progress_a2_onboarding_a0_returns_a2(app, db_session):
    """Progress at A2 is higher than onboarding A0 → 'A2'."""
    a0 = _make_level(db_session, code="A0", order=0)
    a2 = _make_level(db_session, code="A2", order=2)
    user = _make_user(db_session, onboarding_level="A0")
    module = _make_module(db_session, a2)
    lesson = _make_lesson(db_session, module)
    _complete_lesson(db_session, user, lesson)
    result = get_user_current_cefr_level(user.id, db)
    assert result == "A2"


def test_progress_b1_onboarding_c1_returns_c1(app, db_session):
    """Onboarding C1 is higher than progress B1 → 'C1'."""
    b1 = _make_level(db_session, code="B1", order=4)
    c1 = _make_level(db_session, code="C1", order=6)
    user = _make_user(db_session, onboarding_level="C1")
    module = _make_module(db_session, b1)
    lesson = _make_lesson(db_session, module)
    _complete_lesson(db_session, user, lesson)
    result = get_user_current_cefr_level(user.id, db)
    assert result == "C1"


def test_highest_completed_level_is_returned(app, db_session):
    """When progress spans multiple levels, the highest is returned."""
    a1 = _make_level(db_session, code="A1", order=1)
    b2 = _make_level(db_session, code="B2", order=5)
    user = _make_user(db_session, onboarding_level=None)
    for lvl in (a1, b2):
        mod = _make_module(db_session, lvl)
        les = _make_lesson(db_session, mod)
        _complete_lesson(db_session, user, les)
    result = get_user_current_cefr_level(user.id, db)
    assert result == "B2"


def test_onboarding_level_not_in_db_falls_back_to_progress(app, db_session):
    """If onboarding_level code doesn't exist in CEFRLevel, progress wins."""
    a1 = _make_level(db_session, code="A1", order=1)
    user = _make_user(db_session, onboarding_level="XXXX")  # non-existent code
    mod = _make_module(db_session, a1)
    les = _make_lesson(db_session, mod)
    _complete_lesson(db_session, user, les)
    result = get_user_current_cefr_level(user.id, db)
    assert result == "A1"


def test_onboarding_level_not_in_db_and_no_progress_returns_a0(app, db_session):
    """Non-existent onboarding code and no progress → 'A0'."""
    user = _make_user(db_session, onboarding_level="XXXX")
    result = get_user_current_cefr_level(user.id, db)
    assert result == "A0"
