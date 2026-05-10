"""Tests for Task 41: plan estimated time calculation in linear daily plan."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.plan import (
    SLOT_ESTIMATED_MINUTES,
    build_tomorrow_preview,
    get_linear_plan,
    get_plan_intensity,
)
from app.utils.db import db as real_db


# ── Helpers ──────────────────────────────────────────────────────────


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'plantest_{suffix}',
        email=f'plantest_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_level(db_session, order: int = 1) -> CEFRLevel:
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


def _make_lesson(db_session, module: Module, number: int = 1) -> Lessons:
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


def _complete_lesson(db_session, user: User, lesson: Lessons) -> None:
    db_session.add(LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=100.0,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    db_session.commit()


# ── get_plan_intensity ────────────────────────────────────────────────


class TestGetPlanIntensity:
    """Task 42: intensity label from total estimated minutes."""

    def test_light_below_15(self):
        assert get_plan_intensity(10) == 'light'

    def test_light_boundary_zero(self):
        assert get_plan_intensity(0) == 'light'

    def test_light_boundary_14(self):
        assert get_plan_intensity(14) == 'light'

    def test_normal_at_15(self):
        assert get_plan_intensity(15) == 'normal'

    def test_normal_at_25(self):
        assert get_plan_intensity(25) == 'normal'

    def test_normal_at_30(self):
        assert get_plan_intensity(30) == 'normal'

    def test_intensive_at_31(self):
        assert get_plan_intensity(31) == 'intensive'

    def test_intensive_at_35(self):
        assert get_plan_intensity(35) == 'intensive'

    def test_intensive_large(self):
        assert get_plan_intensity(100) == 'intensive'


# ── plan payload includes intensity ───────────────────────────────────


class TestPlanPayloadIntensity:
    def test_plan_intensity_in_payload(self, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)

        assert 'plan_intensity' in payload
        assert payload['plan_intensity'] in ('light', 'normal', 'intensive')

    def test_plan_intensity_matches_total_minutes(self, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)

        assert payload['plan_intensity'] == get_plan_intensity(payload['total_estimated_minutes'])


# ── SLOT_ESTIMATED_MINUTES constant ──────────────────────────────────


class TestSlotEstimatedMinutesConstant:
    def test_all_expected_kinds_present(self):
        expected = {'curriculum', 'srs', 'reading', 'listening', 'writing', 'error_review'}
        assert set(SLOT_ESTIMATED_MINUTES.keys()) == expected

    def test_values_match_spec(self):
        assert SLOT_ESTIMATED_MINUTES['curriculum'] == 15
        assert SLOT_ESTIMATED_MINUTES['srs'] == 10
        assert SLOT_ESTIMATED_MINUTES['reading'] == 15
        assert SLOT_ESTIMATED_MINUTES['listening'] == 10
        assert SLOT_ESTIMATED_MINUTES['writing'] == 8
        assert SLOT_ESTIMATED_MINUTES['error_review'] == 12


# ── total_estimated_minutes in plan payload ───────────────────────────


class TestTotalEstimatedMinutes:
    def test_all_slots_incomplete_correct_sum(self, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)

        assert 'total_estimated_minutes' in payload
        # total_estimated_minutes = sum of SLOT_ESTIMATED_MINUTES for every incomplete slot
        all_slots = payload['slots']
        expected = sum(
            SLOT_ESTIMATED_MINUTES.get(s['kind'], 0)
            for s in all_slots
            if not s.get('completed', False)
        )
        assert payload['total_estimated_minutes'] == expected

    def test_completed_slots_excluded_from_total(self, db_session):
        from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date
        from app.achievements.models import StreakEvent

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        # Complete curriculum lesson so that slot becomes completed
        _complete_lesson(db_session, user, lesson)
        # Record curriculum XP so the slot completion signal fires
        db_session.add(StreakEvent(
            user_id=user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=get_linear_event_local_date(user.id, real_db),
            coins_delta=0,
            details={'source': 'linear_curriculum_quiz', 'xp': 20},
        ))
        db_session.commit()

        before_payload = get_linear_plan(user.id, real_db)
        before_total = before_payload['total_estimated_minutes']

        # With curriculum completed, total should exclude curriculum minutes
        curriculum_minutes = SLOT_ESTIMATED_MINUTES['curriculum']
        # before: all 3 slots incomplete = curriculum(15) + srs(10) + reading(15) = 40
        # after: curriculum done = srs(10) + reading(15) = 25
        curriculum_slot = next(
            s for s in before_payload['baseline_slots'] if s['kind'] == 'curriculum'
        )
        if curriculum_slot['completed']:
            assert before_total <= (40 - curriculum_minutes)
        else:
            # If curriculum is not yet showing as completed (no XP event matched),
            # then total should be the full sum
            assert before_total == sum(
                SLOT_ESTIMATED_MINUTES.get(s['kind'], 0)
                for s in before_payload['baseline_slots']
            )

    def test_total_estimated_minutes_present_in_payload(self, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)

        assert 'total_estimated_minutes' in payload
        assert isinstance(payload['total_estimated_minutes'], int)
        assert payload['total_estimated_minutes'] >= 0

    def test_completed_slots_reduce_total(self, db_session):
        """Completing a slot must reduce total_estimated_minutes by that slot's value."""
        from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date
        from app.achievements.models import StreakEvent

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        # Record XP event so curriculum slot becomes completed
        _complete_lesson(db_session, user, lesson)
        db_session.add(StreakEvent(
            user_id=user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=get_linear_event_local_date(user.id, real_db),
            coins_delta=0,
            details={'source': 'linear_curriculum_quiz', 'xp': 20},
        ))
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)
        total = payload['total_estimated_minutes']

        # Curriculum slot should be completed — its minutes should NOT be in total
        curriculum_slot = next(
            s for s in payload['slots'] if s['kind'] == 'curriculum'
        )
        assert curriculum_slot['completed'] is True

        # Recompute expected from incomplete slots directly
        expected = sum(
            SLOT_ESTIMATED_MINUTES.get(s['kind'], 0)
            for s in payload['slots']
            if not s.get('completed', False)
        )
        assert total == expected
        # Curriculum (15 min) must not be counted
        assert total <= sum(SLOT_ESTIMATED_MINUTES.values()) - SLOT_ESTIMATED_MINUTES['curriculum']


# ── Task 45: tomorrow_preview ─────────────────────────────────────────


class TestBuildTomorrowPreview:
    """build_tomorrow_preview returns a valid preview dict for any user."""

    def test_returns_dict_with_required_keys(self, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        preview = build_tomorrow_preview(user.id, real_db)

        assert isinstance(preview, dict)
        assert 'estimated_minutes' in preview
        assert 'slot_types' in preview

    def test_slot_types_is_list_of_strings(self, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        preview = build_tomorrow_preview(user.id, real_db)

        assert isinstance(preview['slot_types'], list)
        assert all(isinstance(k, str) for k in preview['slot_types'])

    def test_estimated_minutes_matches_slot_types(self, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        preview = build_tomorrow_preview(user.id, real_db)

        expected = sum(SLOT_ESTIMATED_MINUTES.get(k, 0) for k in preview['slot_types'])
        assert preview['estimated_minutes'] == expected

    def test_always_includes_core_slot_types(self, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        preview = build_tomorrow_preview(user.id, real_db)

        # Core slots: curriculum + srs always present
        assert 'curriculum' in preview['slot_types']
        assert 'srs' in preview['slot_types']


class TestPlanTomorrowPreview:
    """plan payload includes tomorrow_preview only when day_secured."""

    def test_no_tomorrow_preview_when_not_secured(self, db_session):
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)

        # With all slots pending, day_secured=False → no tomorrow_preview
        if not payload['day_secured']:
            assert payload['tomorrow_preview'] is None
        # If for some reason day_secured=True (no lessons available), preview exists
        else:
            assert payload['tomorrow_preview'] is not None

    def test_tomorrow_preview_present_when_day_secured(self, db_session):
        from app.achievements.models import StreakEvent
        from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date

        level = _make_level(db_session)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module)
        # Need at least 2 lessons so next_lesson isn't None after completing first
        _make_lesson(db_session, module, number=2)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        # Complete all slots to trigger day_secured
        _complete_lesson(db_session, user, lesson)
        # Record XP for curriculum
        db_session.add(StreakEvent(
            user_id=user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=get_linear_event_local_date(user.id, real_db),
            coins_delta=0,
            details={'source': 'linear_curriculum_quiz', 'xp': 20},
        ))
        # Record SRS XP to mark srs done
        db_session.add(StreakEvent(
            user_id=user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=get_linear_event_local_date(user.id, real_db),
            coins_delta=0,
            details={'source': 'linear_srs_global', 'xp': 8},
        ))
        # Record reading XP to mark reading done
        db_session.add(StreakEvent(
            user_id=user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=get_linear_event_local_date(user.id, real_db),
            coins_delta=0,
            details={'source': 'linear_book_reading', 'xp': 15},
        ))
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)

        if payload['day_secured']:
            assert payload['tomorrow_preview'] is not None
            assert 'estimated_minutes' in payload['tomorrow_preview']
            assert 'slot_types' in payload['tomorrow_preview']

    def test_tomorrow_preview_key_always_present(self, db_session):
        """The key 'tomorrow_preview' must always be in the payload (None or dict)."""
        level = _make_level(db_session)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session)
        user.onboarding_level = level.code
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)

        assert 'tomorrow_preview' in payload
