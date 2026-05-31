"""Tests for the unified daily plan (required / optional / setup).

Covers the acceptance criteria documented in the design plan:
- Fresh user sees a meaningful first step (lesson_1 vocabulary).
- day_secured only closes via required (setup/optional excluded).
- Empty content (no eligible lesson, no history) does NOT generate a
  false «Курс пройден» milestone — surfaces setup_level instead.
- has_more_optional signals correctly.
- Optional items dedup against required by id.
- get_daily_plan_unified edge cases: paused, no-lessons, past pause date.
- compute_day_secured_from_activity edge cases: missing _plan_meta, paused mode.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.plan import build_optional, build_required, build_setup, get_daily_plan
from app.utils.db import db as real_db
from tests.conftest import unique_level_code


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
        code = unique_level_code()
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


class TestOptionalCurriculumStability:
    """Tests for the optional curriculum item not duplicating or disappearing.

    Bug: when done_today=False, both required and optional builders call
    find_next_lesson_linear() and get the same lesson id. The optional
    candidate collides with required and is silently dropped. Fix: pass
    exclude_lesson_ids={required_lesson_id} to the optional builder.
    """

    def test_optional_curriculum_differs_from_required_not_done_today(
        self, db_session,
    ):
        """With two pending lessons, optional curriculum returns L2, not L1.

        Before the fix, both builders resolved to L1 and the optional item
        was dropped by the de-dup check. After the fix, optional uses
        exclude_lesson_ids to skip L1 and find L2.
        """
        level = _make_level(db_session, order=5)
        module = _make_module(db_session, level)
        lesson1 = _make_lesson(db_session, module, number=1, type_='vocabulary')
        lesson2 = _make_lesson(db_session, module, number=2, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        plan = get_daily_plan(user.id, real_db)

        required_curriculum = [it for it in plan['required'] if it['kind'] == 'curriculum']
        optional_curriculum = [it for it in plan['optional'] if it['kind'] == 'curriculum']

        assert len(required_curriculum) == 1
        assert required_curriculum[0]['data']['lesson_id'] == lesson1.id, (
            'Required curriculum should be the first pending lesson'
        )
        assert len(optional_curriculum) == 1, (
            'Optional curriculum item should exist (second lesson available)'
        )
        assert optional_curriculum[0]['data']['lesson_id'] == lesson2.id, (
            'Optional curriculum should be the second lesson, not a duplicate of required'
        )

    def test_optional_curriculum_after_done_today_returns_next(self, db_session):
        """When L1 is done today, optional curriculum should offer L2.

        Required shows L1 as done_today (id=curriculum:lesson:L1).
        Optional should resolve to L2 (next on the spine) with exclude_lesson_ids
        ensuring L1 is skipped even though done_today path already filters it out
        via LessonProgress. This test verifies the happy path remains correct.
        """
        level = _make_level(db_session, order=6)
        module = _make_module(db_session, level)
        lesson1 = _make_lesson(db_session, module, number=1, type_='vocabulary')
        lesson2 = _make_lesson(db_session, module, number=2, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, lesson1)

        plan = get_daily_plan(user.id, real_db)

        required_curriculum = [it for it in plan['required'] if it['kind'] == 'curriculum']
        optional_curriculum = [it for it in plan['optional'] if it['kind'] == 'curriculum']

        assert len(required_curriculum) == 1
        assert required_curriculum[0]['data']['lesson_id'] == lesson1.id
        assert required_curriculum[0]['completed'] is True
        assert len(optional_curriculum) == 1, (
            'Optional curriculum should offer the next lesson after the one done today'
        )
        assert optional_curriculum[0]['data']['lesson_id'] == lesson2.id

    def test_single_remaining_lesson_no_phantom_optional_curriculum(
        self, db_session,
    ):
        """When only one lesson exists and it is done, optional has no curriculum.

        Required shows the done lesson; optional curriculum builder finds no next
        lesson after it (find_next_lesson_linear returns None) and returns None.
        No phantom item should appear.
        """
        level = _make_level(db_session, order=7)
        module = _make_module(db_session, level)
        lesson1 = _make_lesson(db_session, module, number=1, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, lesson1)

        plan = get_daily_plan(user.id, real_db)

        optional_curriculum = [it for it in plan['optional'] if it['kind'] == 'curriculum']
        assert optional_curriculum == [], (
            'No optional curriculum when only one lesson exists and it is done'
        )

    def test_optional_curriculum_ids_distinct_from_required(self, db_session):
        """General invariant: no curriculum id appears in both required and optional."""
        level = _make_level(db_session, order=8)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, number=1, type_='vocabulary')
        _make_lesson(db_session, module, number=2, type_='vocabulary')
        _make_lesson(db_session, module, number=3, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        plan = get_daily_plan(user.id, real_db)

        required_curriculum_ids = {
            it['id'] for it in plan['required'] if it['kind'] == 'curriculum'
        }
        optional_curriculum_ids = {
            it['id'] for it in plan['optional'] if it['kind'] == 'curriculum'
        }
        assert required_curriculum_ids.isdisjoint(optional_curriculum_ids), (
            'Curriculum item id must not appear in both required and optional'
        )


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

    def test_compute_day_secured_missing_plan_meta_returns_false(self):
        """When _plan_meta key is missing entirely, falls back to payload day_secured."""
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {'required': [], 'day_secured': False}
        assert compute_day_secured_from_activity(plan, {}) is False

    def test_compute_day_secured_paused_mode_returns_payload_value(self):
        """In paused mode day_secured reflects the stored payload value."""
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {
            'day_secured': True,
            '_plan_meta': {'effective_mode': 'paused'},
        }
        assert compute_day_secured_from_activity(plan, {}) is True

    def test_compute_day_secured_paused_mode_false(self):
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {
            'day_secured': False,
            '_plan_meta': {'effective_mode': 'paused'},
        }
        assert compute_day_secured_from_activity(plan, {}) is False

    def test_compute_day_secured_item_already_completed_in_payload(self):
        """Items with completed=True in the plan count without completion dict entry."""
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {
            'required': [
                {'id': 'curriculum:lesson:1', 'kind': 'curriculum', 'completed': True},
            ],
            '_plan_meta': {'effective_mode': 'unified'},
        }
        assert compute_day_secured_from_activity(plan, {}) is True


# ── get_daily_plan_unified edge cases ────────────────────────────────


class TestGetDailyPlanUnifiedEdgeCases:

    @pytest.mark.smoke
    def test_no_lessons_available_returns_valid_payload(self, db_session):
        """When no lessons exist for the user's level, get_daily_plan_unified
        still returns a valid payload (not 500) with required=[] or setup hints."""
        user = _make_user(db_session, onboarding_level='C2')

        from app.daily_plan.service import get_daily_plan_unified
        payload = get_daily_plan_unified(user.id)

        assert 'required' in payload
        assert 'optional' in payload
        assert 'setup' in payload
        assert isinstance(payload['required'], list)
        assert payload.get('day_secured') is False

    def test_plan_paused_until_past_does_not_block_plan(self, db_session):
        """When plan_paused_until is yesterday, the plan is NOT paused."""
        yesterday = date.today() - timedelta(days=1)
        user = _make_user(db_session, onboarding_level='A1', plan_paused_until=yesterday)

        from app.daily_plan.service import get_daily_plan_unified
        payload = get_daily_plan_unified(user.id)

        assert payload.get('mode') != 'paused', (
            "past plan_paused_until must not keep the plan in paused state"
        )

    def test_plan_paused_until_today_does_not_block_plan(self, db_session):
        """When plan_paused_until is today (not strictly > today), plan is active."""
        today = date.today()
        user = _make_user(db_session, onboarding_level='A1', plan_paused_until=today)

        from app.daily_plan.service import get_daily_plan_unified
        payload = get_daily_plan_unified(user.id)

        assert payload.get('mode') != 'paused', (
            "plan_paused_until == today should not block the plan (strict > check)"
        )

    def test_plan_paused_until_future_returns_paused_payload(self, db_session):
        """When plan_paused_until is tomorrow, mode=paused is returned."""
        tomorrow = date.today() + timedelta(days=1)
        user = _make_user(db_session, onboarding_level='A1', plan_paused_until=tomorrow)

        from app.daily_plan.service import get_daily_plan_unified
        payload = get_daily_plan_unified(user.id)

        assert payload.get('mode') == 'paused'
        assert 'paused_until' in payload

    def test_total_estimated_minutes_non_negative_no_lessons(self, db_session):
        """total_estimated_minutes is >= 0 even when no required items exist."""
        user = _make_user(db_session, onboarding_level='C2')

        plan = get_daily_plan(user.id, real_db)

        assert plan['total_estimated_minutes'] >= 0

    def test_total_estimated_minutes_non_negative_with_lesson(self, db_session):
        """total_estimated_minutes is >= 0 when required items exist."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module)
        user = _make_user(db_session, onboarding_level='A1')

        plan = get_daily_plan(user.id, real_db)

        assert plan['total_estimated_minutes'] >= 0

    def test_unified_payload_has_plan_meta(self, db_session):
        """get_daily_plan_unified always attaches _plan_meta with effective_mode."""
        user = _make_user(db_session, onboarding_level='C2')

        from app.daily_plan.service import get_daily_plan_unified
        payload = get_daily_plan_unified(user.id)

        assert '_plan_meta' in payload
        assert payload['_plan_meta']['effective_mode'] in ('unified', 'paused')

    def test_unified_fallback_payload_on_assembly_error(self, db_session, monkeypatch):
        """If plan assembly raises, get_daily_plan_unified returns safe fallback."""
        user = _make_user(db_session, onboarding_level='A1')

        def _boom(*args, **kwargs):
            raise RuntimeError("injected failure")

        import app.daily_plan.plan as plan_mod
        monkeypatch.setattr(plan_mod, 'get_daily_plan', _boom)

        from app.daily_plan.service import get_daily_plan_unified
        payload = get_daily_plan_unified(user.id)

        assert payload['mode'] == 'unified'
        assert payload['required'] == []
        assert payload['day_secured'] is False
        assert payload['_plan_meta']['fallback_reason'] == 'unified_build_failed'


# ── Grammar review item (Task 3) ─────────────────────────────────────


def _make_grammar_topic(db_session, level: str = 'A1', order: int = 1) -> Any:
    from app.grammar_lab.models import GrammarTopic

    slug = f'test-topic-{uuid.uuid4().hex[:8]}'
    topic = GrammarTopic()
    topic.slug = slug
    topic.title = f'Topic {slug}'
    topic.title_ru = f'Тема {slug}'
    topic.level = level
    topic.order = order
    topic.content = {}
    db_session.add(topic)
    db_session.commit()
    return topic


class TestGrammarReviewItemBuilder:
    """Unit tests for build_grammar_review_item via mocks (no DB needed)."""

    def test_returns_none_when_no_topics_exist(self, app):
        """No GrammarTopic rows → returns None."""
        from unittest.mock import MagicMock
        from app.daily_plan.items.grammar_review import build_grammar_review_item

        db = MagicMock()
        db.session.get.return_value = None

        # Both history and fallback queries return None.
        query_chain = db.session.query.return_value
        query_chain.join.return_value = query_chain
        query_chain.filter.return_value = query_chain
        query_chain.group_by.return_value = query_chain
        query_chain.order_by.return_value = query_chain
        query_chain.first.return_value = None

        with app.app_context():
            result = build_grammar_review_item(user_id=1, db=db)
        assert result is None

    def test_returns_plan_item_with_correct_kind(self, db_session):
        """With a grammar topic, builder returns a grammar_review PlanItem."""
        from app.daily_plan.items.grammar_review import build_grammar_review_item

        topic = _make_grammar_topic(db_session, level='A1')
        user = _make_user(db_session, onboarding_level='A1')

        item = build_grammar_review_item(user_id=user.id, db=real_db)

        assert item is not None
        assert item.kind == 'grammar_review'
        assert item.id == f'grammar_review:topic:{topic.id}'
        assert item.url == f'/grammar-lab/topic/{topic.slug}'
        assert item.eta_minutes == 10
        assert item.completed is False

    def test_item_id_is_stable(self, db_session):
        """Same user + same topic → same item id on repeated calls."""
        from app.daily_plan.items.grammar_review import build_grammar_review_item

        _make_grammar_topic(db_session, level='A1')
        user = _make_user(db_session, onboarding_level='A1')

        item1 = build_grammar_review_item(user_id=user.id, db=real_db)
        item2 = build_grammar_review_item(user_id=user.id, db=real_db)

        assert item1 is not None and item2 is not None
        assert item1.id == item2.id

    def test_level_fallback_when_no_history(self, db_session):
        """User with no UserGrammarExercise history → level fallback topic returned."""
        from app.daily_plan.items.grammar_review import build_grammar_review_item

        topic_a1 = _make_grammar_topic(db_session, level='A1', order=1)
        _make_grammar_topic(db_session, level='B1', order=1)
        user = _make_user(db_session, onboarding_level='A1')

        item = build_grammar_review_item(user_id=user.id, db=real_db)

        assert item is not None
        # Should pick the A1 topic because that's the user's level.
        assert item.data['topic_level'] == 'A1'
        assert item.data['topic_id'] == topic_a1.id


class TestGraduatedStatePlan:
    """Integration tests for graduated user behaviour in the plan."""

    def test_graduated_flag_false_for_mid_course_user(self, db_session):
        """User with a pending lesson → graduated=False in payload."""
        level = _make_level(db_session, order=9)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, number=1, type_='vocabulary')
        _make_lesson(db_session, module, number=2, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        plan = get_daily_plan(user.id, real_db)
        assert plan.get('graduated') is False

    def test_graduated_flag_true_when_all_lessons_done(self, db_session):
        """User who finished all lessons → graduated=True in payload."""
        level = _make_level(db_session, order=10)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, number=1, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, lesson)

        plan = get_daily_plan(user.id, real_db)
        assert plan.get('graduated') is True

    def test_graduated_flag_false_with_no_history(self, db_session):
        """User on C2 with no lessons and no history → graduated=False (not yet started)."""
        user = _make_user(db_session, onboarding_level='C2')

        plan = get_daily_plan(user.id, real_db)
        assert plan.get('graduated') is False

    def test_graduated_user_optional_contains_grammar_review(self, db_session):
        """Graduated user (all done) with a grammar topic → grammar_review in optional."""
        level = _make_level(db_session, order=11)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, number=1, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, lesson)
        _make_grammar_topic(db_session, level=level.code)

        plan = get_daily_plan(user.id, real_db)

        optional_kinds = [it['kind'] for it in plan['optional']]
        assert 'grammar_review' in optional_kinds, (
            'Graduated user should see grammar_review in optional when topics exist'
        )

    def test_graduated_user_setup_has_book_not_level(self, db_session):
        """Graduated user: setup_level must NOT appear (has history), setup_book may appear."""
        level = _make_level(db_session, order=12)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, number=1, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, lesson)

        plan = get_daily_plan(user.id, real_db)

        setup_kinds = [it['kind'] for it in plan['setup']]
        assert 'setup_level' not in setup_kinds, (
            'Graduated user must not see setup_level'
        )
        assert 'setup_book' in setup_kinds, (
            'Graduated user without reading pref should see setup_book'
        )

    def test_grammar_review_appears_in_optional_priority_order(self, db_session):
        """grammar_review appears AFTER srs in _OPTIONAL_PRIORITY."""
        from app.daily_plan.plan import _OPTIONAL_PRIORITY
        priority = list(_OPTIONAL_PRIORITY)
        assert 'grammar_review' in priority
        assert 'srs' in priority
        srs_pos = priority.index('srs')
        gr_pos = priority.index('grammar_review')
        assert srs_pos < gr_pos, 'srs must appear before grammar_review in _OPTIONAL_PRIORITY'


class TestSRSIgnoreDailyBudget:
    """Tests for build_srs_item with ignore_daily_budget=True."""

    def test_ignore_daily_budget_surfaces_done_item_in_optional(self, app):
        """With ignore_daily_budget=True, 'done today' SRS item not filtered in optional."""
        from unittest.mock import MagicMock, patch
        from app.daily_plan.items.srs import build_srs_item

        with app.app_context():
            with patch('app.daily_plan.items.srs._srs_completed_today', return_value=True), \
                 patch('app.daily_plan.linear.slots.srs_slot.count_linear_plan_srs_due_cards', return_value=0), \
                 patch('app.daily_plan.linear.slots.srs_slot.count_srs_reviews_today', return_value=5), \
                 patch('app.srs.counting.count_due_cards', return_value=0), \
                 patch('app.srs.counting.get_new_card_budget', return_value=(0, 0)), \
                 patch('app.srs.counting.count_new_cards_today', return_value=0), \
                 patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'), \
                 patch('app.study.models.StudySettings.get_settings') as mock_settings:
                mock_settings.return_value = MagicMock(reviews_per_day=30)

                db = MagicMock()
                item = build_srs_item(1, db, section='optional', ignore_daily_budget=True)

        assert item is not None, (
            'ignore_daily_budget=True must surface SRS item even when done today in optional'
        )
        assert item.completed is True

    def test_without_ignore_daily_budget_filters_done_optional(self, app):
        """Without the flag, the default behaviour still filters done SRS from optional."""
        from unittest.mock import MagicMock, patch
        from app.daily_plan.items.srs import build_srs_item

        with app.app_context():
            with patch('app.daily_plan.items.srs._srs_completed_today', return_value=True), \
                 patch('app.daily_plan.linear.slots.srs_slot.count_linear_plan_srs_due_cards', return_value=0):
                db = MagicMock()
                item = build_srs_item(1, db, section='optional')

        assert item is None, (
            'Default behaviour: done SRS with no due cards filtered from optional'
        )


# ── Task 4: day_secured in graduated state ───────────────────────────


class TestGraduatedDaySecured:
    """compute_day_secured_from_activity for graduated users.

    (a) graduated user with no activity today → day_secured False
    (b) graduated user with SRS reviews → day_secured True
    """

    def _graduated_plan(self, user_id: int) -> dict:
        return {
            'required': [],
            'optional': [],
            'setup': [],
            'graduated': True,
            '_plan_meta': {
                'effective_mode': 'unified',
                'graduated': True,
                'user_id': user_id,
            },
        }

    def test_graduated_no_activity_day_not_secured(self, db_session):
        """Graduated user with zero activity today → day_secured=False."""
        from unittest.mock import patch
        from app.daily_plan.service import compute_day_secured_from_activity

        user = _make_user(db_session, onboarding_level='A1')
        plan = self._graduated_plan(user.id)

        with patch('app.utils.activity_tracker.has_learning_activity', return_value=False):
            result = compute_day_secured_from_activity(plan, {})

        assert result is False

    def test_graduated_with_activity_day_secured(self, db_session):
        """Graduated user who has activity today → day_secured=True."""
        from unittest.mock import patch
        from app.daily_plan.service import compute_day_secured_from_activity

        user = _make_user(db_session, onboarding_level='A1')
        plan = self._graduated_plan(user.id)

        with patch('app.utils.activity_tracker.has_learning_activity', return_value=True):
            result = compute_day_secured_from_activity(plan, {})

        assert result is True

    def test_non_graduated_empty_required_still_returns_false(self):
        """Non-graduated empty required → day_secured=False (unchanged behaviour)."""
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {
            'required': [],
            '_plan_meta': {
                'effective_mode': 'unified',
                'graduated': False,
                'user_id': 999,
            },
        }
        assert compute_day_secured_from_activity(plan, {}) is False

    def test_graduated_flag_stamped_in_plan_meta_by_service(self, db_session):
        """get_daily_plan_unified stamps graduated=True in _plan_meta for a graduated user."""
        level = _make_level(db_session, order=20)
        module = _make_module(db_session, level)
        lesson = _make_lesson(db_session, module, number=1, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, lesson)

        from app.daily_plan.service import get_daily_plan_unified
        payload = get_daily_plan_unified(user.id)

        meta = payload.get('_plan_meta', {})
        assert meta.get('graduated') is True, (
            'graduated=True must be stamped in _plan_meta for a graduated user'
        )
        assert meta.get('user_id') == user.id, (
            'user_id must be stamped in _plan_meta'
        )
