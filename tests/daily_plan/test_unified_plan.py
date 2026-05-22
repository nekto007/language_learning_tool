"""Tests for the unified daily plan (required / optional / setup).

Covers the acceptance criteria documented in the design plan:
- Fresh user sees a meaningful first step (lesson_1 vocabulary).
- day_secured only closes via required (setup/optional excluded).
- Empty content (no eligible lesson, no history) does NOT generate a
  false «Курс пройден» milestone — surfaces setup_level instead.
- has_more_optional signals correctly.
- Optional items dedup against required by id.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.plan import build_optional, build_required, build_setup, get_daily_plan
from app.utils.db import db as real_db


# ── Helpers ──────────────────────────────────────────────────────────


def _make_user(db_session, **kwargs) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'unifiedplan_{suffix}',
        email=f'unifiedplan_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    for k, v in kwargs.items():
        setattr(user, k, v)
    db_session.add(user)
    db_session.commit()
    return user


def _make_level(db_session, code: str | None = None, order: int = 1) -> CEFRLevel:
    if code is None:
        code = uuid.uuid4().hex[:2].upper()
    level = CEFRLevel(code=code, name=f'Level {code}', description='', order=order)
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level: CEFRLevel, number: int = 1) -> Module:
    module = Module(
        level_id=level.id,
        number=number,
        title=f'{level.code} M{number}',
        description='',
        raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(
    db_session, module: Module, number: int = 1, type_: str = 'vocabulary',
) -> Lessons:
    lesson = Lessons(
        module_id=module.id,
        number=number,
        title=f'{module.title} L{number}',
        type=type_,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _complete_lesson(db_session, user: User, lesson: Lessons) -> None:
    db_session.add(LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=100.0,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    db_session.commit()


# ── Required composition ─────────────────────────────────────────────


class TestRequiredComposition:

    @pytest.mark.smoke
    def test_fresh_user_required_has_first_curriculum_lesson(self, db_session):
        """Fresh user (no history, no due cards, no book) → first lesson
        in required, setup_book in setup. Day NOT secured (uncompleted)."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, type_='vocabulary')
        user = _make_user(db_session, onboarding_level='A1')

        plan = get_daily_plan(user.id, real_db)

        assert plan['mode'] == 'unified'
        assert len(plan['required']) >= 1
        # First required is the curriculum lesson (no due cards for new user).
        curriculum_items = [it for it in plan['required'] if it['kind'] == 'curriculum']
        assert len(curriculum_items) == 1
        assert curriculum_items[0]['data']['lesson_id'] == lesson.id

    def test_required_excludes_reading_when_no_book(self, db_session):
        """Reading slot does NOT enter required when user has no book."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, type_='vocabulary')
        user = _make_user(db_session, onboarding_level='A1')

        plan = get_daily_plan(user.id, real_db)

        reading_required = [it for it in plan['required'] if it['kind'] == 'reading']
        assert reading_required == []

    def test_day_secured_false_at_assembly(self, db_session):
        """Assembly-time day_secured is always False (items start uncompleted)."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session, onboarding_level='A1')

        plan = get_daily_plan(user.id, real_db)
        assert plan['day_secured'] is False


# ── No false milestones (the original bug) ───────────────────────────


class TestNoFalseMilestones:

    @pytest.mark.smoke
    def test_no_eligible_content_no_history_does_NOT_say_course_complete(
        self, db_session,
    ):
        """User with no eligible curriculum content AND no completion history
        sees ``position=None`` but the orchestrator does NOT mark anything as
        complete and does NOT emit a course-complete milestone. Instead a
        setup_level item appears in setup."""
        # User on C2 but no level / module / lesson exists for them.
        user = _make_user(db_session, onboarding_level='C2')

        plan = get_daily_plan(user.id, real_db)

        assert plan['position'] is None
        # No curriculum item in required (no lesson available).
        assert all(it['kind'] != 'curriculum' for it in plan['required'])
        # setup_level surfaces instead.
        setup_kinds = [it['kind'] for it in plan['setup']]
        assert 'setup_level' in setup_kinds

    def test_no_history_no_lesson_required_is_empty_or_setup_only(
        self, db_session,
    ):
        """Fresh user with empty catalogue: required may be empty AND day
        cannot be secured. setup hints the user to act."""
        user = _make_user(db_session, onboarding_level='C2')

        plan = get_daily_plan(user.id, real_db)

        # day_secured must be False whenever required is empty.
        assert plan['day_secured'] is False
        # Empty required is permitted in this edge case.
        if not plan['required']:
            assert plan['setup'], 'setup must guide the user when required is empty'

    def test_genuinely_completed_user_does_not_get_setup_level(self, db_session):
        """User who has completed lessons but has no next eligible lesson
        (e.g., reached the end of their level) does NOT get setup_level —
        course completion is a milestone, not a setup hint."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, type_='vocabulary')
        user = _make_user(db_session, onboarding_level='A1')
        _complete_lesson(db_session, user, lesson)

        plan = get_daily_plan(user.id, real_db)

        # No next lesson → position None, but user has history.
        assert plan['position'] is None
        # setup_level should NOT appear (history present).
        setup_kinds = [it['kind'] for it in plan['setup']]
        assert 'setup_level' not in setup_kinds


# ── Setup ─────────────────────────────────────────────────────────────


class TestSetup:

    @pytest.mark.smoke
    def test_setup_book_when_no_preference(self, db_session):
        """User without UserReadingPreference sees setup_book."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session, onboarding_level='A1')

        plan = get_daily_plan(user.id, real_db)

        setup_kinds = [it['kind'] for it in plan['setup']]
        assert 'setup_book' in setup_kinds

    def test_setup_book_url_opens_modal(self, db_session):
        user = _make_user(db_session, onboarding_level='A1')

        plan = get_daily_plan(user.id, real_db)

        setup_book_items = [it for it in plan['setup'] if it['kind'] == 'setup_book']
        assert setup_book_items, 'setup_book item missing'
        assert setup_book_items[0]['url'] == '#book-select-modal'


# ── Optional ─────────────────────────────────────────────────────────


class TestOptional:

    def test_optional_dedups_against_required(self, db_session):
        """Items already in required must not duplicate in optional."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, number=1, type_='vocabulary')
        _make_lesson(db_session, module, number=2, type_='vocabulary')
        user = _make_user(db_session, onboarding_level='A1')

        plan = get_daily_plan(user.id, real_db)

        required_ids = {it['id'] for it in plan['required']}
        optional_ids = {it['id'] for it in plan['optional']}
        assert required_ids.isdisjoint(optional_ids), (
            'Optional must not duplicate required items'
        )

    def test_has_more_optional_flag_present(self, db_session):
        """``has_more_optional`` must be a boolean in the payload."""
        user = _make_user(db_session, onboarding_level='A1')
        plan = get_daily_plan(user.id, real_db)
        assert isinstance(plan.get('has_more_optional'), bool)


# ── Payload contract ─────────────────────────────────────────────────


class TestPayloadContract:

    @pytest.mark.smoke
    def test_payload_has_all_three_sections(self, db_session):
        """Every payload contains required/optional/setup keys (may be empty)."""
        user = _make_user(db_session, onboarding_level='A1')
        plan = get_daily_plan(user.id, real_db)
        assert 'required' in plan
        assert 'optional' in plan
        assert 'setup' in plan
        assert isinstance(plan['required'], list)
        assert isinstance(plan['optional'], list)
        assert isinstance(plan['setup'], list)

    def test_payload_mode_is_unified(self, db_session):
        user = _make_user(db_session, onboarding_level='A1')
        plan = get_daily_plan(user.id, real_db)
        assert plan['mode'] == 'unified'

    def test_total_estimated_minutes_sums_required_only(self, db_session):
        """ETA in payload only sums incomplete required items."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session, onboarding_level='A1')

        plan = get_daily_plan(user.id, real_db)
        expected = sum(it['eta_minutes'] for it in plan['required']
                       if not it.get('completed'))
        assert plan['total_estimated_minutes'] == expected


# ── compute_day_secured_from_activity for unified ────────────────────


class TestUnifiedDaySecured:
    """Verify the API-layer day_secured evaluator handles unified payload."""

    def test_unified_day_not_secured_when_empty_required(self):
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {'required': [], 'optional': [], 'setup': [], '_plan_meta': {'effective_mode': 'unified'}}
        assert compute_day_secured_from_activity(plan, {}) is False

    def test_unified_day_secured_when_all_required_complete(self):
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {
            'required': [
                {'id': 'curriculum:lesson:1', 'kind': 'curriculum', 'completed': False},
                {'id': 'srs:global', 'kind': 'srs', 'completed': False},
            ],
            '_plan_meta': {'effective_mode': 'unified'},
        }
        completion = {'curriculum:lesson:1': True, 'srs:global': True}
        assert compute_day_secured_from_activity(plan, completion) is True

    def test_unified_day_not_secured_when_partial(self):
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {
            'required': [
                {'id': 'curriculum:lesson:1', 'kind': 'curriculum', 'completed': False},
                {'id': 'srs:global', 'kind': 'srs', 'completed': False},
            ],
            '_plan_meta': {'effective_mode': 'unified'},
        }
        completion = {'curriculum:lesson:1': True, 'srs:global': False}
        assert compute_day_secured_from_activity(plan, completion) is False
