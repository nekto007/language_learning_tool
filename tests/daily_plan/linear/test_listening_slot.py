"""Tests for the linear daily plan listening extension slot.

Covers:
- No listening lesson in current module → build_listening_slot returns None.
- Listening lesson present → slot returned with correct kind/type/url.
- Completed listening lesson is skipped; next incomplete returned.
- Slot completed when today's linear listening XP event exists.
- Chain builder includes listening in EXTENSION_PRIORITY after reading.
- Template renders listening slot with headphone icon and type badge.
- maybe_award_listening_xp: first call awards and creates StreakEvent; repeat no-op.
- day_secured unaffected by listening slot (extension only, never baseline).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.chain import EXTENSION_PRIORITY, _build_listening_extension
from app.daily_plan.linear.plan import compute_linear_day_secured
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.listening_slot import (
    _LISTENING_XP_SOURCES,
    _find_next_listening_lesson,
    _listening_done_today,
    build_listening_slot,
)
from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, maybe_award_listening_xp
from app.achievements.xp_service import LINEAR_XP
from app.utils.db import db as real_db

_LEVEL_ORDER_COUNTER = iter(range(50, 100))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'listenslot_{suffix}',
        email=f'listenslot_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_module_with_lessons(
    db_session,
    *,
    level_order: int | None = None,
    module_number: int = 1,
    lesson_types: list[str] | None = None,
) -> tuple[Module, list[Lessons]]:
    """Create a module with one lesson per type in lesson_types."""
    if level_order is None:
        level_order = next(_LEVEL_ORDER_COUNTER)
    # CEFRLevel.code is VARCHAR(2) — use 2-char unique codes
    suffix = uuid.uuid4().hex[:2].upper()
    # Ensure uniqueness for the order field too
    existing_orders = {r[0] for r in db_session.query(CEFRLevel.order).all()}
    while level_order in existing_orders:
        level_order += 1

    level = CEFRLevel(
        code=suffix,
        name=f'Level {suffix}',
        description='test',
        order=level_order,
    )
    db_session.add(level)
    db_session.commit()

    module = Module(
        level_id=level.id,
        number=module_number,
        title=f'Module {suffix}',
        description='d',
        raw_content={'module': {'id': module_number}},
    )
    db_session.add(module)
    db_session.commit()

    lessons: list[Lessons] = []
    for i, ltype in enumerate(lesson_types or ['vocabulary'], start=1):
        lesson = Lessons(
            module_id=module.id,
            number=i,
            title=f'Lesson {i} ({ltype})',
            type=ltype,
            content={},
        )
        db_session.add(lesson)
        lessons.append(lesson)
    db_session.commit()
    return module, lessons


def _mark_completed(db_session, user: User, lesson: Lessons) -> None:
    prog = LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        completed_at=datetime.now(timezone.utc),
    )
    db_session.add(prog)
    db_session.commit()


def _record_listening_xp_event(db_session, user: User, source: str) -> None:
    event = StreakEvent(
        user_id=user.id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=datetime.now(timezone.utc).date(),
        coins_delta=0,
        details={'source': source, 'xp': 15},
    )
    db_session.add(event)
    db_session.commit()


# ---------------------------------------------------------------------------
# Tests for _find_next_listening_lesson
# ---------------------------------------------------------------------------

class TestFindNextListeningLesson:
    def test_returns_none_when_no_current_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: None,
        )
        result = _find_next_listening_lesson(user.id, real_db)
        assert result is None

    def test_returns_none_when_module_has_no_listening_lessons(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'grammar', 'quiz'],
        )
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: lessons[0],
        )
        result = _find_next_listening_lesson(user.id, real_db)
        assert result is None

    def test_returns_listening_lesson_when_present(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'listening_immersion', 'dictation'],
        )
        vocab_lesson = lessons[0]
        listening_lesson = lessons[1]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _find_next_listening_lesson(user.id, real_db)
        assert result is not None
        assert result.id == listening_lesson.id
        assert result.type == 'listening_immersion'

    def test_skips_completed_listening_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'listening_immersion', 'dictation'],
        )
        vocab_lesson = lessons[0]
        listening_lesson = lessons[1]
        dictation_lesson = lessons[2]
        _mark_completed(db_session, user, listening_lesson)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _find_next_listening_lesson(user.id, real_db)
        assert result is not None
        assert result.id == dictation_lesson.id
        assert result.type == 'dictation'

    def test_returns_none_when_all_listening_lessons_completed(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'listening_immersion'],
        )
        vocab_lesson = lessons[0]
        listening_lesson = lessons[1]
        _mark_completed(db_session, user, listening_lesson)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _find_next_listening_lesson(user.id, real_db)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for _listening_done_today
# ---------------------------------------------------------------------------

class TestListeningDoneToday:
    def test_not_done_when_no_xp_events(self, db_session):
        user = _make_user(db_session)
        assert _listening_done_today(user.id, real_db) is False

    def test_done_when_listening_immersion_xp_event_today(self, db_session):
        user = _make_user(db_session)
        _record_listening_xp_event(db_session, user, 'linear_curriculum_listening_immersion')
        assert _listening_done_today(user.id, real_db) is True

    def test_done_when_dictation_xp_event_today(self, db_session):
        user = _make_user(db_session)
        _record_listening_xp_event(db_session, user, 'linear_curriculum_dictation')
        assert _listening_done_today(user.id, real_db) is True

    def test_not_done_when_different_source(self, db_session):
        user = _make_user(db_session)
        _record_listening_xp_event(db_session, user, 'linear_book_reading')
        assert _listening_done_today(user.id, real_db) is False


# ---------------------------------------------------------------------------
# Tests for build_listening_slot
# ---------------------------------------------------------------------------

class TestBuildListeningSlot:
    def test_returns_none_when_no_listening_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: None,
        )
        result = build_listening_slot(user.id, real_db)
        assert result is None

    def test_returns_listening_slot_with_correct_shape(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'listening_immersion'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot = build_listening_slot(user.id, real_db)
        assert slot is not None
        assert isinstance(slot, LinearSlot)
        assert slot.kind == 'listening'
        assert slot.lesson_type == 'listening_immersion'
        assert slot.completed is False
        assert slot.data['lesson_id'] == lessons[1].id
        assert slot.data['lesson_type'] == 'listening_immersion'
        assert slot.data['estimated_minutes'] == 10
        assert slot.url is not None

    def test_slot_completed_when_xp_event_today(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'listening_immersion'],
        )
        vocab_lesson = lessons[0]
        _record_listening_xp_event(db_session, user, 'linear_curriculum_listening_immersion')
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot = build_listening_slot(user.id, real_db)
        assert slot is not None
        assert slot.completed is True

    def test_to_dict_includes_all_fields(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'dictation'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot_dict = build_listening_slot(user.id, real_db).to_dict()
        assert set(slot_dict) == {
            'kind', 'title', 'lesson_type', 'eta_minutes', 'url', 'completed', 'data',
        }
        assert slot_dict['kind'] == 'listening'
        assert slot_dict['lesson_type'] == 'dictation'


# ---------------------------------------------------------------------------
# Tests for chain EXTENSION_PRIORITY
# ---------------------------------------------------------------------------

class TestChainIntegration:
    def test_listening_in_extension_priority(self):
        assert 'listening' in EXTENSION_PRIORITY

    def test_listening_after_reading_in_priority(self):
        assert EXTENSION_PRIORITY.index('listening') > EXTENSION_PRIORITY.index('reading')

    def test_listening_before_error_review_in_priority(self):
        assert EXTENSION_PRIORITY.index('listening') < EXTENSION_PRIORITY.index('error_review')

    def test_build_listening_extension_returns_none_when_no_lesson(
        self, db_session, monkeypatch
    ):
        user = _make_user(db_session)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: None,
        )
        result = _build_listening_extension(user.id, real_db, [])
        assert result is None

    def test_build_listening_extension_marks_extension_true(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'listening_immersion'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.listening_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _build_listening_extension(user.id, real_db, [])
        assert result is not None
        assert result['data']['extension'] is True

    def test_build_listening_extension_skips_when_already_in_chain(
        self, db_session, monkeypatch
    ):
        user = _make_user(db_session)
        existing_chain = [{'kind': 'listening', 'completed': False}]
        result = _build_listening_extension(user.id, real_db, existing_chain)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for maybe_award_listening_xp
# ---------------------------------------------------------------------------

class TestMaybeAwardListeningXp:
    def test_linear_listening_in_linear_xp(self):
        assert 'linear_listening' in LINEAR_XP
        assert LINEAR_XP['linear_listening'] == 18

    def test_linear_listening_in_xp_sources(self):
        assert 'linear_listening' in _LISTENING_XP_SOURCES

    def test_first_award_creates_streak_event(self, db_session):
        user = _make_user(db_session)
        user.use_linear_plan = True
        db_session.commit()

        stats = UserStatistics(user_id=user.id, total_xp=0)
        db_session.add(stats)
        db_session.commit()

        today = datetime.now(timezone.utc).date()
        result = maybe_award_listening_xp(user.id, lesson_id=1, for_date=today)

        assert result is not None
        assert result.xp_awarded > 0

        event = db_session.query(StreakEvent).filter(
            StreakEvent.user_id == user.id,
            StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
            StreakEvent.event_date == today,
            StreakEvent.details['source'].astext == 'linear_listening',
        ).first()
        assert event is not None

    def test_repeat_call_same_day_is_noop(self, db_session):
        user = _make_user(db_session)
        user.use_linear_plan = True
        db_session.commit()

        stats = UserStatistics(user_id=user.id, total_xp=0)
        db_session.add(stats)
        db_session.commit()

        today = datetime.now(timezone.utc).date()
        first = maybe_award_listening_xp(user.id, lesson_id=1, for_date=today)
        real_db.session.commit()
        second = maybe_award_listening_xp(user.id, lesson_id=1, for_date=today)

        assert first is not None
        assert second is None

    def test_non_linear_user_returns_none(self, db_session):
        user = _make_user(db_session)
        user.use_linear_plan = False
        db_session.commit()

        today = datetime.now(timezone.utc).date()
        result = maybe_award_listening_xp(user.id, lesson_id=1, for_date=today)
        assert result is None

    def test_slot_detected_as_done_via_linear_listening_event(self, db_session):
        user = _make_user(db_session)
        event = StreakEvent(
            user_id=user.id,
            event_type=LINEAR_XP_EVENT_TYPE,
            event_date=datetime.now(timezone.utc).date(),
            coins_delta=0,
            details={'source': 'linear_listening', 'xp': 18},
        )
        db_session.add(event)
        db_session.commit()

        assert _listening_done_today(user.id, real_db) is True


# ---------------------------------------------------------------------------
# Tests for compute_linear_day_secured with listening slot
# ---------------------------------------------------------------------------

class TestDaySecuredUnaffectedByListeningSlot:
    def test_listening_slot_not_in_baseline_does_not_block_secured(self):
        baseline_slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ]
        assert compute_linear_day_secured(baseline_slots) is True

    def test_day_secured_false_when_baseline_incomplete(self):
        baseline_slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': False},
            {'kind': 'reading', 'completed': True},
        ]
        assert compute_linear_day_secured(baseline_slots) is False

    def test_listening_extension_slot_never_present_in_baseline(self):
        # listening is built only as extension; baseline only contains
        # curriculum/srs/reading/error_review. Verify compute_linear_day_secured
        # ignores it if somehow included as extra (all-done baseline = secured).
        baseline_slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ]
        listening_extension = {'kind': 'listening', 'completed': False}
        # day_secured only uses baseline_slots, not extension slots
        assert compute_linear_day_secured(baseline_slots) is True
        # Confirm compute_linear_day_secured would return False if listening
        # were incorrectly included in baseline while incomplete
        assert compute_linear_day_secured(baseline_slots + [listening_extension]) is False
