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
    """Tests for the optional curriculum continuation queue.

    Optional now carries a Duolingo-style queue of upcoming spine lessons
    starting strictly AFTER the required anchor lesson (in spine order),
    never duplicating the required item. These tests assert the queue
    invariants on small spines (the head of the queue = next lesson after
    required); ``TestOptionalContinuationQueue`` covers longer spines.
    """

    def test_optional_curriculum_differs_from_required_not_done_today(
        self, db_session,
    ):
        """With two pending lessons, the optional queue starts at L2, not L1.

        Required anchors on L1 (first pending lesson). The continuation queue
        begins strictly after the anchor, so its head is L2 — never a
        duplicate of the required item.
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
        # Queue starts after the required anchor (L1), in spine order.
        queue_ids = [it['data']['lesson_id'] for it in optional_curriculum]
        assert queue_ids == [lesson2.id], (
            'Optional queue head should be the next lesson after required'
        )

    def test_optional_curriculum_after_done_today_returns_next(self, db_session):
        """When L1 is done today, the optional queue head is L2.

        Required shows L1 as done_today (id=curriculum:lesson:L1, completed).
        The continuation queue anchors on that required lesson and offers L2
        (the next lesson on the spine) as its head.
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
        queue_ids = [it['data']['lesson_id'] for it in optional_curriculum]
        assert queue_ids == [lesson2.id], (
            'Optional queue head should be the next lesson after the one done today'
        )

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
        """General invariant: no curriculum id appears in both required and optional.

        With three pending lessons the queue lists L2, L3 in spine order, all
        distinct from the required anchor L1.
        """
        level = _make_level(db_session, order=8)
        module = _make_module(db_session, level)
        l1 = _make_lesson(db_session, module, number=1, type_='vocabulary')
        l2 = _make_lesson(db_session, module, number=2, type_='vocabulary')
        l3 = _make_lesson(db_session, module, number=3, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        plan = get_daily_plan(user.id, real_db)

        required_curriculum_ids = {
            it['id'] for it in plan['required'] if it['kind'] == 'curriculum'
        }
        optional_curriculum = [it for it in plan['optional'] if it['kind'] == 'curriculum']
        optional_curriculum_ids = {it['id'] for it in optional_curriculum}
        assert required_curriculum_ids.isdisjoint(optional_curriculum_ids), (
            'Curriculum item id must not appear in both required and optional'
        )
        # Queue carries the upcoming spine lessons in order, after the anchor.
        assert [it['data']['lesson_id'] for it in optional_curriculum] == [l2.id, l3.id]
        assert l1.id not in {it['data']['lesson_id'] for it in optional_curriculum}


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

    def test_unified_day_not_secured_when_required_item_skipped(self):
        """Skipped required slots remove navigation but do not satisfy the minimum."""
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {
            'required': [
                {
                    'id': 'curriculum:lesson:1',
                    'kind': 'curriculum',
                    'completed': False,
                    'skipped': True,
                },
            ],
            '_plan_meta': {'effective_mode': 'unified'},
        }
        assert compute_day_secured_from_activity(plan, {}) is False

    def test_unified_day_not_secured_when_required_item_blocked(self):
        """Blocked dependent required slots do not count as completed work."""
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {
            'required': [
                {
                    'id': 'listening:lesson:2',
                    'kind': 'listening',
                    'completed': False,
                    'blocked': True,
                },
            ],
            '_plan_meta': {'effective_mode': 'unified'},
        }
        assert compute_day_secured_from_activity(plan, {}) is False

    def test_unified_day_not_secured_when_only_completed_required_plus_blocked_dependency(self):
        """A blocked required dependency still keeps the day unsecured."""
        from app.daily_plan.service import compute_day_secured_from_activity

        plan = {
            'required': [
                {'id': 'curriculum:lesson:1', 'kind': 'curriculum', 'completed': True},
                {
                    'id': 'listening:lesson:2',
                    'kind': 'listening',
                    'completed': False,
                    'blocked': True,
                },
            ],
            '_plan_meta': {'effective_mode': 'unified'},
        }
        assert compute_day_secured_from_activity(plan, {}) is False


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
        from app.daily_plan.service import get_daily_plan_unified
        from app.utils.time_utils import get_user_local_date

        user = _make_user(db_session, onboarding_level='A1')
        # Anchor on the user-local date the service compares against — using
        # server-local date.today() flakes near midnight when the server tz
        # leads the user's (UTC fallback) tz.
        user.plan_paused_until = get_user_local_date(user.id) - timedelta(days=1)
        db_session.flush()
        payload = get_daily_plan_unified(user.id)

        assert payload.get('mode') != 'paused', (
            "past plan_paused_until must not keep the plan in paused state"
        )

    def test_plan_paused_until_today_does_not_block_plan(self, db_session):
        """When plan_paused_until is today (not strictly > today), plan is active."""
        from app.daily_plan.service import get_daily_plan_unified
        from app.utils.time_utils import get_user_local_date

        user = _make_user(db_session, onboarding_level='A1')
        user.plan_paused_until = get_user_local_date(user.id)
        db_session.flush()
        payload = get_daily_plan_unified(user.id)

        assert payload.get('mode') != 'paused', (
            "plan_paused_until == today should not block the plan (strict > check)"
        )

    def test_plan_paused_until_future_returns_paused_payload(self, db_session):
        """When plan_paused_until is tomorrow, mode=paused is returned."""
        from app.daily_plan.service import get_daily_plan_unified
        from app.utils.time_utils import get_user_local_date

        user = _make_user(db_session, onboarding_level='A1')
        user.plan_paused_until = get_user_local_date(user.id) + timedelta(days=1)
        db_session.flush()
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
        # Bug #1 fix: link the practice queue (where the user does
        # exercises), not the topic detail page (theory only).
        assert item.url == f'/grammar-lab/practice/topic/{topic.id}'
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
        # Grammar topic must use a public CEFR code so topic_detail never 404s.
        _make_grammar_topic(db_session, level='A1')

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
        from unittest.mock import patch
        from app.daily_plan.items.srs import build_srs_item

        with app.app_context():
            with patch('app.daily_plan.items.srs._srs_completed_today', return_value=True), \
                 patch('app.daily_plan.linear.slots.srs_slot.count_srs_reviews_today', return_value=5), \
                 patch('app.srs.counting.count_pending_new', return_value=0), \
                 patch('app.srs.counting.count_due_by_states', return_value=0), \
                 patch('app.srs.counting.get_new_card_budget', return_value=(0, 0)), \
                 patch('app.srs.counting.count_new_cards_today', return_value=0), \
                 patch('app.srs.counting.count_reviews_today', return_value=5), \
                 patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'):
                db = object()
                item = build_srs_item(1, db, section='optional', ignore_daily_budget=True)

        assert item is not None, (
            'ignore_daily_budget=True must surface SRS item even when done today in optional'
        )
        assert item.completed is True

    def test_without_ignore_daily_budget_filters_done_optional(self, app):
        """Without the flag, the default behaviour still filters done SRS from optional."""
        from unittest.mock import patch
        from app.daily_plan.items.srs import build_srs_item

        with app.app_context():
            with patch('app.daily_plan.items.srs._srs_completed_today', return_value=True), \
                 patch('app.daily_plan.linear.slots.srs_slot.count_srs_reviews_today', return_value=0), \
                 patch('app.srs.counting.count_pending_new', return_value=0), \
                 patch('app.srs.counting.count_due_by_states', return_value=0), \
                 patch('app.srs.counting.get_new_card_budget', return_value=(0, 0)), \
                 patch('app.srs.counting.count_new_cards_today', return_value=0), \
                 patch('app.srs.counting.count_reviews_today', return_value=0), \
                 patch('app.study.services.SRSService.get_adaptive_limit_reason', return_value='normal'):
                db = object()
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


# ── Task 1: continuation queue (build_curriculum_queue) ──────────────────────


class TestBuildCurriculumQueue:
    """Unit tests for build_curriculum_queue — the Duolingo-style continuation
    queue of upcoming spine lessons after the required anchor lesson."""

    def test_queue_returns_n_lessons_in_spine_order(self, db_session):
        """Queue returns the next ``limit`` lessons after the anchor, in order."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level = _make_level(db_session, order=30)
        module = _make_module(db_session, level)
        anchor = _make_lesson(db_session, module, number=1, type_='vocabulary')
        l2 = _make_lesson(db_session, module, number=2, type_='vocabulary')
        l3 = _make_lesson(db_session, module, number=3, type_='vocabulary')
        l4 = _make_lesson(db_session, module, number=4, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=2,
        )

        assert [it.data['lesson_id'] for it in items] == [l2.id, l3.id]
        # queue_position is 1-based and sequential.
        assert [it.data['queue_position'] for it in items] == [1, 2]
        assert all(it.section == 'optional' for it in items)
        assert all(it.kind == 'curriculum' for it in items)
        assert all(it.completed is False for it in items)
        assert l4.id not in {it.data['lesson_id'] for it in items}

    def test_queue_does_not_include_anchor(self, db_session):
        """The anchor lesson never appears in its own continuation queue."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level = _make_level(db_session, order=31)
        module = _make_module(db_session, level)
        anchor = _make_lesson(db_session, module, number=1, type_='vocabulary')
        _make_lesson(db_session, module, number=2, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=10,
        )

        assert anchor.id not in {it.data['lesson_id'] for it in items}

    def test_queue_crosses_module_and_level_boundary(self, db_session):
        """Queue spans module / level boundaries like the spine itself."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level1 = _make_level(db_session, order=32)
        level2 = _make_level(db_session, order=33)
        m1 = _make_module(db_session, level1, number=1)
        m2 = _make_module(db_session, level1, number=2)
        m3 = _make_module(db_session, level2, number=1)
        anchor = _make_lesson(db_session, m1, number=1, type_='vocabulary')
        l_m2 = _make_lesson(db_session, m2, number=1, type_='vocabulary')
        l_m3 = _make_lesson(db_session, m3, number=1, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level1.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=10,
        )

        ids = [it.data['lesson_id'] for it in items]
        assert ids == [l_m2.id, l_m3.id], (
            'Queue must cross module and level boundaries in spine order'
        )

    def test_queue_excludes_blocked_module_lessons(self, db_session):
        """A hard-blocked module drops the rest of its level from the queue.

        The route's ``check_module_access`` gates a non-first module on the
        *previous* module reaching 80% completion. A hard-blocked module can
        never reach 80%, so its same-level successor (``m3`` here) is
        transitively unreachable and would 403 if previewed — it must not
        dangle in the queue even though it carries no explicit prerequisites.
        """
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level = _make_level(db_session, order=34)
        m1 = _make_module(db_session, level, number=1)
        m2 = _make_module(db_session, level, number=2)
        m3 = _make_module(db_session, level, number=3)
        anchor = _make_lesson(db_session, m1, number=1, type_='vocabulary')
        # m2 is gated on completing m1 (anchor is incomplete → blocked).
        m2.prerequisites = [{'type': 'module', 'id': m1.id}]
        l_m2 = _make_lesson(db_session, m2, number=1, type_='vocabulary')
        l_m3 = _make_lesson(db_session, m3, number=1, type_='vocabulary')
        db_session.commit()
        user = _make_user(db_session, onboarding_level=level.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=10,
        )

        ids = {it.data['lesson_id'] for it in items}
        assert l_m2.id not in ids, 'Blocked-module lesson must not appear in queue'
        assert l_m3.id not in ids, (
            'Same-level module after a hard block is transitively gated by the '
            "route's previous-module 80% rule and must not dangle in the queue"
        )

    def test_queue_resumes_on_new_level_after_block(self, db_session):
        """A hard block stops the current level but not a later level's first module."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level1 = _make_level(db_session, order=37)
        level2 = _make_level(db_session, order=38)
        m1 = _make_module(db_session, level1, number=1)
        m2 = _make_module(db_session, level1, number=2)
        m3 = _make_module(db_session, level1, number=3)
        n1 = _make_module(db_session, level2, number=1)
        anchor = _make_lesson(db_session, m1, number=1, type_='vocabulary')
        # m2 hard-blocked → m2 and same-level m3 are dropped, but level2's
        # first module is auto-accessible and should still preview.
        m2.prerequisites = [{'type': 'module', 'id': m1.id}]
        l_m2 = _make_lesson(db_session, m2, number=1, type_='vocabulary')
        l_m3 = _make_lesson(db_session, m3, number=1, type_='vocabulary')
        l_n1 = _make_lesson(db_session, n1, number=1, type_='vocabulary')
        db_session.commit()
        user = _make_user(db_session, onboarding_level=level1.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=10,
        )

        ids = [it.data['lesson_id'] for it in items]
        assert l_m2.id not in ids
        assert l_m3.id not in ids
        assert ids == [l_n1.id], (
            'Queue should resume at the next level’s first module after a block'
        )

    def test_queue_pages_past_large_blocked_level(self, db_session):
        """A blocked level larger than one fetch window still resumes next level.

        The same-level hard-block fix drops every later module of a blocked
        level. On a realistic CEFR level (dozens of lessons) those rejected
        lessons exceed any single over-fetch window, so the builder must *page*
        the spine — not fetch once — or it returns an empty queue and a false
        ``has_more_optional`` even though the next level's first module is
        eligible. The dropped block here spans more lessons than the internal
        batch size, exercising the multi-batch path.
        """
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level1 = _make_level(db_session, order=41)
        level2 = _make_level(db_session, order=42)
        m1 = _make_module(db_session, level1, number=1)
        m2 = _make_module(db_session, level1, number=2)
        m3 = _make_module(db_session, level1, number=3)
        n1 = _make_module(db_session, level2, number=1)
        anchor = _make_lesson(db_session, m1, number=1, type_='vocabulary')
        # m2 hard-blocked → m2 and same-level m3 are dropped. m3 alone carries
        # more lessons than a single fetch batch, so a one-shot over-fetch
        # would never reach level2.
        m2.prerequisites = [{'type': 'module', 'id': m1.id}]
        _make_lesson(db_session, m2, number=1, type_='vocabulary')
        for n in range(1, 41):  # 40 dropped same-level lessons (> batch size)
            _make_lesson(db_session, m3, number=n, type_='vocabulary')
        l_n1 = _make_lesson(db_session, n1, number=1, type_='vocabulary')
        db_session.commit()
        user = _make_user(db_session, onboarding_level=level1.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=2,
        )

        ids = [it.data['lesson_id'] for it in items]
        assert ids == [l_n1.id], (
            'Queue must page past a large blocked level and resume at the next '
            "level's first module instead of starving on the dropped window"
        )

    def test_queue_respects_exclude_lesson_ids(self, db_session):
        """exclude_lesson_ids removes specific lessons from the queue."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level = _make_level(db_session, order=35)
        module = _make_module(db_session, level)
        anchor = _make_lesson(db_session, module, number=1, type_='vocabulary')
        l2 = _make_lesson(db_session, module, number=2, type_='vocabulary')
        l3 = _make_lesson(db_session, module, number=3, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=10,
            exclude_lesson_ids={l2.id},
        )

        ids = [it.data['lesson_id'] for it in items]
        assert l2.id not in ids
        assert ids == [l3.id]

    def test_queue_empty_when_single_remaining_lesson(self, db_session):
        """When anchor is the last lesson, the queue is empty."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level = _make_level(db_session, order=36)
        module = _make_module(db_session, level)
        anchor = _make_lesson(db_session, module, number=1, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=10,
        )

        assert items == []

    def test_queue_empty_when_anchor_is_none(self, db_session):
        """A None anchor (graduated user) yields an empty queue, not an error."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        user = _make_user(db_session)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=None, limit=10,
        )

        assert items == []

    def test_queue_empty_when_limit_non_positive(self, db_session):
        """A non-positive limit yields an empty queue without touching the DB."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level = _make_level(db_session, order=37)
        module = _make_module(db_session, level)
        anchor = _make_lesson(db_session, module, number=1, type_='vocabulary')
        _make_lesson(db_session, module, number=2, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        assert build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=0,
        ) == []
        assert build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=-5,
        ) == []

    def test_queue_items_carry_url_and_level_code(self, db_session):
        """Queue items populate url/eta and the level_code flips at a boundary."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level1 = _make_level(db_session, order=38)
        level2 = _make_level(db_session, order=39)
        m1 = _make_module(db_session, level1, number=1)
        m2 = _make_module(db_session, level2, number=1)
        anchor = _make_lesson(db_session, m1, number=1, type_='vocabulary')
        l_m1 = _make_lesson(db_session, m1, number=2, type_='vocabulary')
        l_m2 = _make_lesson(db_session, m2, number=1, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level1.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=10,
        )

        by_lesson = {it.data['lesson_id']: it for it in items}
        assert by_lesson[l_m1.id].data['level_code'] == level1.code
        assert by_lesson[l_m2.id].data['level_code'] == level2.code
        assert all(it.url for it in items)
        assert all(it.eta_minutes is not None for it in items)

    def test_queue_caps_at_limit_when_more_available(self, db_session):
        """With more pending lessons than ``limit``, the builder returns exactly
        ``limit`` items (the over-fetch detector relies on this boundary)."""
        from app.daily_plan.items.curriculum import build_curriculum_queue

        level = _make_level(db_session, order=40)
        module = _make_module(db_session, level)
        anchor = _make_lesson(db_session, module, number=1, type_='vocabulary')
        # 5 pending lessons after the anchor, ask for 3.
        for n in range(2, 7):
            _make_lesson(db_session, module, number=n, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        items = build_curriculum_queue(
            user.id, real_db, anchor_lesson=anchor, limit=3,
        )

        assert len(items) == 3
        # queue_position is 1-based and contiguous up to the cap.
        assert [it.data['queue_position'] for it in items] == [1, 2, 3]


# ── Task 2: continuation queue wired into build_optional ─────────────────────


class TestOptionalContinuationQueue:
    """Optional now carries a continuation queue of upcoming spine lessons
    (Task 2) instead of a single next-lesson curriculum candidate."""

    def test_optional_has_multiple_curriculum_lessons_in_order(self, db_session):
        """≥3 pending lessons → optional lists the upcoming lessons in spine order."""
        level = _make_level(db_session, order=40)
        module = _make_module(db_session, level)
        l1 = _make_lesson(db_session, module, number=1, type_='vocabulary')
        l2 = _make_lesson(db_session, module, number=2, type_='vocabulary')
        l3 = _make_lesson(db_session, module, number=3, type_='vocabulary')
        l4 = _make_lesson(db_session, module, number=4, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        plan = get_daily_plan(user.id, real_db)

        required_curriculum = [it for it in plan['required'] if it['kind'] == 'curriculum']
        assert len(required_curriculum) == 1
        assert required_curriculum[0]['data']['lesson_id'] == l1.id

        optional_curriculum = [it for it in plan['optional'] if it['kind'] == 'curriculum']
        ids = [it['data']['lesson_id'] for it in optional_curriculum]
        # Queue starts after the required anchor (L1), in spine order.
        assert ids == [l2.id, l3.id, l4.id], (
            'Optional must carry the upcoming lessons in spine order'
        )

    def test_optional_queue_does_not_duplicate_required(self, db_session):
        """No curriculum id appears in both required and optional."""
        level = _make_level(db_session, order=41)
        module = _make_module(db_session, level)
        for n in range(1, 6):
            _make_lesson(db_session, module, number=n, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        plan = get_daily_plan(user.id, real_db)

        required_ids = {it['id'] for it in plan['required']}
        optional_ids = {it['id'] for it in plan['optional']}
        assert required_ids.isdisjoint(optional_ids)

    def test_has_more_optional_is_boolean_with_queue(self, db_session):
        """has_more_optional remains a bool when a long queue is present."""
        level = _make_level(db_session, order=42)
        module = _make_module(db_session, level)
        for n in range(1, 6):
            _make_lesson(db_session, module, number=n, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        plan = get_daily_plan(user.id, real_db)
        assert isinstance(plan['has_more_optional'], bool)

    def test_queue_capped_at_continuation_limit(self, db_session):
        """A very long spine is capped at CONTINUATION_QUEUE_LIMIT in optional."""
        from app.daily_plan.plan import CONTINUATION_QUEUE_LIMIT

        level = _make_level(db_session, order=43)
        module = _make_module(db_session, level)
        for n in range(1, CONTINUATION_QUEUE_LIMIT + 6):
            _make_lesson(db_session, module, number=n, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        plan = get_daily_plan(user.id, real_db)

        optional_curriculum = [it for it in plan['optional'] if it['kind'] == 'curriculum']
        assert len(optional_curriculum) <= CONTINUATION_QUEUE_LIMIT
        # has_more must signal there is content beyond the cap.
        assert plan['has_more_optional'] is True

    def test_day_secured_independent_of_queue_length(self, db_session):
        """day_secured is recomputed from required only — queue length is irrelevant."""
        from app.daily_plan.service import compute_day_secured_from_activity

        level = _make_level(db_session, order=44)
        module = _make_module(db_session, level)
        for n in range(1, 8):
            _make_lesson(db_session, module, number=n, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        from app.daily_plan.service import get_daily_plan_unified
        payload = get_daily_plan_unified(user.id)

        # Mark every required item complete; optional queue stays incomplete.
        completion = {it['id']: True for it in payload['required']}
        assert compute_day_secured_from_activity(payload, completion) is True
        # The long optional queue does not affect the secured verdict.

    def test_single_remaining_lesson_empty_queue(self, db_session):
        """Only one lesson → no continuation queue in optional."""
        level = _make_level(db_session, order=45)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, number=1, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        plan = get_daily_plan(user.id, real_db)

        optional_curriculum = [it for it in plan['optional'] if it['kind'] == 'curriculum']
        assert optional_curriculum == []

    def test_queue_suppressed_when_curriculum_skipped(self, db_session):
        """Skipping the required curriculum lesson suppresses the queue.

        The template unlocks optional via ``u_required_settled`` (a skip
        counts as settled), but every queue lesson is route-gated on the
        previous lesson being completed (``check_lesson_access``). A skipped
        anchor is never completed, so the first queue lesson would 403 — the
        queue must not surface those dead links.
        """
        from datetime import date

        from app.daily_plan.models import DailyPlanEvent
        from app.utils.time_utils import get_user_local_date

        level = _make_level(db_session, order=46)
        module = _make_module(db_session, level)
        l1 = _make_lesson(db_session, module, number=1, type_='vocabulary')
        _make_lesson(db_session, module, number=2, type_='vocabulary')
        _make_lesson(db_session, module, number=3, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        # Sanity: without a skip the queue is present.
        plan_before = get_daily_plan(user.id, real_db)
        assert [it for it in plan_before['optional'] if it['kind'] == 'curriculum']

        # Skip the required curriculum slot for today.
        today = get_user_local_date(user.id, real_db)
        db_session.add(DailyPlanEvent(
            user_id=user.id,
            event_type='slot_skipped',
            plan_date=today,
            step_kind='curriculum',
        ))
        db_session.commit()

        plan = get_daily_plan(user.id, real_db)

        # The required curriculum anchor is still L1, now marked skipped.
        required_curriculum = [it for it in plan['required'] if it['kind'] == 'curriculum']
        assert len(required_curriculum) == 1
        assert required_curriculum[0]['data']['lesson_id'] == l1.id
        assert required_curriculum[0].get('skipped') is True

        # No curriculum continuation queue while the anchor is skipped.
        optional_curriculum = [it for it in plan['optional'] if it['kind'] == 'curriculum']
        assert optional_curriculum == []

    def test_queue_reappears_when_skipped_lesson_later_completed(self, db_session):
        """Completing the skipped lesson re-opens the queue (same day).

        Suppression keys on the required curriculum item still being
        incomplete, not on the raw skip event. Once the user returns via the
        «Вернуться» CTA and completes the skipped lesson, the required anchor
        flips to the done-today card (``completed=True``) and the next spine
        lesson is route-open — so the continuation queue must reappear even
        though the day's slot_skipped event still exists.
        """
        from app.daily_plan.models import DailyPlanEvent
        from app.utils.time_utils import get_user_local_date

        level = _make_level(db_session, order=47)
        module = _make_module(db_session, level)
        l1 = _make_lesson(db_session, module, number=1, type_='vocabulary')
        l2 = _make_lesson(db_session, module, number=2, type_='vocabulary')
        _make_lesson(db_session, module, number=3, type_='vocabulary')
        user = _make_user(db_session, onboarding_level=level.code)

        # Skip the required curriculum slot for today.
        today = get_user_local_date(user.id, real_db)
        db_session.add(DailyPlanEvent(
            user_id=user.id,
            event_type='slot_skipped',
            plan_date=today,
            step_kind='curriculum',
        ))
        db_session.commit()

        # Queue suppressed while skipped + incomplete.
        plan_skipped = get_daily_plan(user.id, real_db)
        assert [it for it in plan_skipped['optional'] if it['kind'] == 'curriculum'] == []

        # User returns and completes the previously-skipped lesson today; the
        # slot_skipped event is left in place.
        _complete_lesson(db_session, user, l1)

        plan_after = get_daily_plan(user.id, real_db)

        # Required curriculum now shows L1 as the done-today anchor.
        required_curriculum = [it for it in plan_after['required'] if it['kind'] == 'curriculum']
        assert len(required_curriculum) == 1
        assert required_curriculum[0]['data']['lesson_id'] == l1.id
        assert required_curriculum[0].get('completed') is True

        # The continuation queue reappears, anchored after L1 → next is L2.
        optional_curriculum = [it for it in plan_after['optional'] if it['kind'] == 'curriculum']
        assert optional_curriculum, 'Queue must reappear once the lesson is completed'
        assert optional_curriculum[0]['data']['lesson_id'] == l2.id


# ── SRS deck-quiz placement vs card lesson (finding #13) ─────────────────────


def _make_due_review_card(db_session, user_id):
    """Create one due REVIEW card so the SRS slot is non-empty."""
    from app.srs.constants import CardState, DEFAULT_EASE_FACTOR
    from app.study.models import UserCardDirection, UserWord
    from app.words.models import CollectionWords

    suffix = uuid.uuid4().hex[:8]
    word = CollectionWords(
        english_word=f'due_{suffix}', russian_word=f'due_ru_{suffix}', level='A1',
    )
    db_session.add(word)
    db_session.flush()
    uw = UserWord(user_id=user_id, word_id=word.id)
    uw.status = 'review'
    db_session.add(uw)
    db_session.flush()
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    card = UserCardDirection(
        user_word_id=uw.id, direction='eng-rus',
        state=CardState.REVIEW.value, interval=5,
        ease_factor=DEFAULT_EASE_FACTOR, next_review=past,
    )
    db_session.add(card)
    db_session.commit()
    return card


class TestSrsDeckQuizPlacement:
    def test_card_lesson_no_decks_keeps_plain_srs_and_dedups_optional(self, db_session):
        """No custom decks: required SRS stays srs:global (not a dead deck-quiz
        placeholder), and the optional duplicate collapses by id (finding #13)."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, type_='card')  # next lesson is a card lesson
        user = _make_user(db_session, onboarding_level='A1')
        _make_due_review_card(db_session, user.id)

        required = build_required(user.id, real_db, difficulty='intensive', focus=None)
        srs_required = [it for it in required if it.kind == 'srs']
        assert len(srs_required) == 1
        assert srs_required[0].id == 'srs:global'

        optional, _ = build_optional(
            user.id, real_db, required_items=required, focus=None,
        )
        # The would-be optional srs:global is the same id as required → collapsed.
        assert [it for it in optional if it.kind == 'srs'] == []

    def test_card_lesson_with_decks_uses_deck_quiz(self, db_session, monkeypatch):
        """With custom-deck words the required SRS becomes a deck quiz."""
        level = _make_level(db_session, code='A1', order=1)
        module = _make_module(db_session, level)
        _make_lesson(db_session, module, type_='card')
        user = _make_user(db_session, onboarding_level='A1')
        _make_due_review_card(db_session, user.id)

        monkeypatch.setattr(
            'app.daily_plan.linear.slots.srs_slot._count_user_deck_quiz_words',
            lambda uid, db: 5,
        )

        required = build_required(user.id, real_db, difficulty='intensive', focus=None)
        srs_required = [it for it in required if it.kind == 'srs']
        assert len(srs_required) == 1
        assert srs_required[0].id == 'srs:deck_quiz'
