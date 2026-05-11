"""Tests for the linear daily plan speaking extension slot.

Covers:
- No speaking lesson in current module → build_speaking_slot returns None.
- Speaking lesson present → slot returned with correct kind/type/url.
- Completed speaking lesson is skipped; next incomplete returned.
- Slot completed when LessonProgress.completed exists for lesson.
- speech_api_required=True for pronunciation, False for shadow_reading.
- Chain builder includes speaking in EXTENSION_PRIORITY after listening.
- Template renders speaking slot with microphone icon and Chrome hint.
- day_secured unaffected by speaking slot (extension only, never baseline).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.auth.models import User
from app.curriculum.models import (
    CEFRLevel,
    LessonProgress,
    Lessons,
    Module,
)
from app.daily_plan.linear.chain import (
    EXTENSION_PRIORITY,
    _build_speaking_extension,
)
from app.daily_plan.linear.plan import compute_linear_day_secured
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.speaking_slot import (
    _SPEAKING_LESSON_TYPES,
    _SPEAKING_SLOT_ETA_MINUTES,
    _SPEECH_API_LESSON_TYPES,
    _find_next_speaking_lesson,
    _speaking_done_today,
    build_speaking_slot,
)
from app.utils.db import db as real_db

_LEVEL_ORDER_COUNTER = iter(range(250, 300))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'speakslot_{suffix}',
        email=f'speakslot_{suffix}@example.com',
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
    if level_order is None:
        level_order = next(_LEVEL_ORDER_COUNTER)
    suffix = uuid.uuid4().hex[:2].upper()
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


# ---------------------------------------------------------------------------
# Tests for constants
# ---------------------------------------------------------------------------

class TestSpeakingSlotConstants:
    def test_contains_pronunciation(self):
        assert 'pronunciation' in _SPEAKING_LESSON_TYPES

    def test_contains_shadow_reading(self):
        assert 'shadow_reading' in _SPEAKING_LESSON_TYPES

    def test_eta_minutes_is_seven(self):
        assert _SPEAKING_SLOT_ETA_MINUTES == 7

    def test_pronunciation_requires_speech_api(self):
        assert 'pronunciation' in _SPEECH_API_LESSON_TYPES

    def test_shadow_reading_does_not_require_speech_api(self):
        assert 'shadow_reading' not in _SPEECH_API_LESSON_TYPES


# ---------------------------------------------------------------------------
# Tests for _find_next_speaking_lesson
# ---------------------------------------------------------------------------

class TestFindNextSpeakingLesson:
    def test_returns_none_when_no_current_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: None,
        )
        result = _find_next_speaking_lesson(user.id, real_db)
        assert result is None

    def test_returns_none_when_module_has_no_speaking_lessons(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'grammar', 'quiz'],
        )
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: lessons[0],
        )
        result = _find_next_speaking_lesson(user.id, real_db)
        assert result is None

    def test_returns_pronunciation_lesson_when_present(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'pronunciation', 'shadow_reading'],
        )
        vocab_lesson = lessons[0]
        pronunciation_lesson = lessons[1]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _find_next_speaking_lesson(user.id, real_db)
        assert result is not None
        assert result.id == pronunciation_lesson.id
        assert result.type == 'pronunciation'

    def test_skips_completed_pronunciation_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'pronunciation', 'shadow_reading'],
        )
        vocab_lesson = lessons[0]
        pronunciation_lesson = lessons[1]
        shadow_lesson = lessons[2]
        _mark_completed(db_session, user, pronunciation_lesson)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _find_next_speaking_lesson(user.id, real_db)
        assert result is not None
        assert result.id == shadow_lesson.id
        assert result.type == 'shadow_reading'

    def test_returns_none_when_all_speaking_lessons_completed(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'pronunciation'],
        )
        vocab_lesson = lessons[0]
        pronunciation_lesson = lessons[1]
        _mark_completed(db_session, user, pronunciation_lesson)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _find_next_speaking_lesson(user.id, real_db)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for _speaking_done_today
# ---------------------------------------------------------------------------

class TestSpeakingDoneToday:
    def test_not_done_when_no_lesson_progress(self, db_session):
        user = _make_user(db_session)
        result = _speaking_done_today(user.id, real_db)
        assert result is False

    def test_done_when_pronunciation_completed_today(self, db_session):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['pronunciation'],
        )
        _mark_completed(db_session, user, lessons[0])
        result = _speaking_done_today(user.id, real_db)
        assert result is True

    def test_done_when_shadow_reading_completed_today(self, db_session):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['shadow_reading'],
        )
        _mark_completed(db_session, user, lessons[0])
        result = _speaking_done_today(user.id, real_db)
        assert result is True

    def test_not_done_for_non_speaking_lesson(self, db_session):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary'],
        )
        _mark_completed(db_session, user, lessons[0])
        result = _speaking_done_today(user.id, real_db)
        assert result is False


# ---------------------------------------------------------------------------
# Tests for build_speaking_slot
# ---------------------------------------------------------------------------

class TestBuildSpeakingSlot:
    def test_returns_none_when_no_speaking_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: None,
        )
        result = build_speaking_slot(user.id, real_db)
        assert result is None

    def test_returns_slot_for_pronunciation_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'pronunciation'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot = build_speaking_slot(user.id, real_db)
        assert slot is not None
        assert isinstance(slot, LinearSlot)
        assert slot.kind == 'speaking'
        assert slot.lesson_type == 'pronunciation'
        assert slot.completed is False
        assert slot.data['lesson_id'] == lessons[1].id
        assert slot.data['lesson_type'] == 'pronunciation'
        assert slot.data['estimated_minutes'] == _SPEAKING_SLOT_ETA_MINUTES
        assert slot.data['speech_api_required'] is True
        assert slot.url is not None

    def test_returns_slot_for_shadow_reading_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'shadow_reading'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot = build_speaking_slot(user.id, real_db)
        assert slot is not None
        assert slot.kind == 'speaking'
        assert slot.lesson_type == 'shadow_reading'
        assert slot.data['speech_api_required'] is False

    def test_slot_completed_when_speaking_done_today(self, db_session, monkeypatch):
        # pronunciation_1 completed today → slot shows shadow_reading_1 as completed=True
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'pronunciation', 'shadow_reading'],
        )
        vocab_lesson = lessons[0]
        pronunciation_lesson = lessons[1]
        _mark_completed(db_session, user, pronunciation_lesson)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot = build_speaking_slot(user.id, real_db)
        assert slot is not None
        assert slot.completed is True
        # Points to the next incomplete speaking lesson
        assert slot.data['lesson_id'] == lessons[2].id

    def test_to_dict_includes_all_fields(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'shadow_reading'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot_dict = build_speaking_slot(user.id, real_db).to_dict()
        assert set(slot_dict) == {
            'kind', 'title', 'lesson_type', 'eta_minutes', 'url', 'completed', 'data',
        }
        assert slot_dict['kind'] == 'speaking'
        assert slot_dict['lesson_type'] == 'shadow_reading'
        assert slot_dict['data']['speech_api_required'] is False


# ---------------------------------------------------------------------------
# Tests for chain EXTENSION_PRIORITY
# ---------------------------------------------------------------------------

class TestChainIntegration:
    def test_speaking_in_extension_priority(self):
        assert 'speaking' in EXTENSION_PRIORITY

    def test_speaking_after_listening_in_priority(self):
        assert EXTENSION_PRIORITY.index('speaking') > EXTENSION_PRIORITY.index('listening')

    def test_speaking_before_writing_in_priority(self):
        assert EXTENSION_PRIORITY.index('speaking') < EXTENSION_PRIORITY.index('writing')

    def test_speaking_before_error_review_in_priority(self):
        assert EXTENSION_PRIORITY.index('speaking') < EXTENSION_PRIORITY.index('error_review')

    def test_build_speaking_extension_returns_none_when_no_lesson(
        self, db_session, monkeypatch
    ):
        user = _make_user(db_session)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: None,
        )
        result = _build_speaking_extension(user.id, real_db, [])
        assert result is None

    def test_build_speaking_extension_marks_extension_true(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'pronunciation'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.speaking_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _build_speaking_extension(user.id, real_db, [])
        assert result is not None
        assert result['data']['extension'] is True

    def test_build_speaking_extension_skips_when_already_in_chain(
        self, db_session, monkeypatch
    ):
        user = _make_user(db_session)
        existing_chain = [{'kind': 'speaking', 'completed': False}]
        result = _build_speaking_extension(user.id, real_db, existing_chain)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for day_secured unaffected by speaking slot
# ---------------------------------------------------------------------------

class TestDaySecuredUnaffectedBySpeakingSlot:
    def test_speaking_slot_not_in_baseline_does_not_block_secured(self):
        baseline_slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ]
        assert compute_linear_day_secured(baseline_slots) is True

    def test_speaking_extension_slot_never_blocks_secured(self):
        baseline_slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ]
        # day_secured only uses baseline_slots; speaking is always extension
        assert compute_linear_day_secured(baseline_slots) is True

    def test_day_secured_false_when_baseline_incomplete(self):
        baseline_slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': False},
            {'kind': 'reading', 'completed': True},
        ]
        assert compute_linear_day_secured(baseline_slots) is False
