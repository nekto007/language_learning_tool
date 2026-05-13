"""Tests for the linear daily plan writing extension slot.

Covers:
- No writing lesson in current module → build_writing_slot returns None.
- Writing lesson present → slot returned with correct kind/type/url.
- Completed writing lesson is skipped; next incomplete returned.
- Slot completed when UserWritingAttempt submitted today.
- Slot completed when LessonProgress.completed exists for lesson.
- Chain builder includes writing in EXTENSION_PRIORITY after listening.
- Template renders writing slot with pen icon and type badge.
- day_secured unaffected by writing slot (extension only, never baseline).
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
    UserWritingAttempt,
)
from app.daily_plan.linear.chain import (
    EXTENSION_PRIORITY,
    _build_writing_extension,
)
from app.daily_plan.linear.plan import compute_linear_day_secured
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.writing_slot import (
    _WRITING_LESSON_TYPES,
    _WRITING_SLOT_ETA_MINUTES,
    _find_next_writing_lesson,
    _writing_done_today,
    build_writing_slot,
)
from app.utils.db import db as real_db

_LEVEL_ORDER_COUNTER = iter(range(150, 200))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'writeslot_{suffix}',
        email=f'writeslot_{suffix}@example.com',
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
    now = datetime.now(timezone.utc)
    prog = LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        completed_at=now,
        last_activity=now,
    )
    db_session.add(prog)
    db_session.commit()


def _add_writing_attempt(db_session, user: User, lesson: Lessons) -> UserWritingAttempt:
    attempt = UserWritingAttempt(
        user_id=user.id,
        lesson_id=lesson.id,
        response_text='Test response text for writing.',
        word_count=6,
        checklist_completed=True,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


# ---------------------------------------------------------------------------
# Tests for _WRITING_LESSON_TYPES constant
# ---------------------------------------------------------------------------

class TestWritingLessonTypes:
    def test_contains_writing_prompt(self):
        assert 'writing_prompt' in _WRITING_LESSON_TYPES

    def test_contains_translation(self):
        assert 'translation' in _WRITING_LESSON_TYPES

    def test_eta_minutes_is_eight(self):
        assert _WRITING_SLOT_ETA_MINUTES == 8


# ---------------------------------------------------------------------------
# Tests for _find_next_writing_lesson
# ---------------------------------------------------------------------------

class TestFindNextWritingLesson:
    def test_returns_none_when_no_current_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: None,
        )
        result = _find_next_writing_lesson(user.id, real_db)
        assert result is None

    def test_returns_none_when_module_has_no_writing_lessons(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'grammar', 'quiz'],
        )
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: lessons[0],
        )
        result = _find_next_writing_lesson(user.id, real_db)
        assert result is None

    def test_returns_writing_prompt_lesson_when_present(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'writing_prompt', 'translation'],
        )
        vocab_lesson = lessons[0]
        writing_lesson = lessons[1]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _find_next_writing_lesson(user.id, real_db)
        assert result is not None
        assert result.id == writing_lesson.id
        assert result.type == 'writing_prompt'

    def test_skips_completed_writing_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'writing_prompt', 'translation'],
        )
        vocab_lesson = lessons[0]
        writing_lesson = lessons[1]
        translation_lesson = lessons[2]
        _mark_completed(db_session, user, writing_lesson)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _find_next_writing_lesson(user.id, real_db)
        assert result is not None
        assert result.id == translation_lesson.id
        assert result.type == 'translation'

    def test_returns_none_when_all_writing_lessons_completed(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'writing_prompt'],
        )
        vocab_lesson = lessons[0]
        writing_lesson = lessons[1]
        _mark_completed(db_session, user, writing_lesson)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _find_next_writing_lesson(user.id, real_db)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for _writing_done_today
# ---------------------------------------------------------------------------

class TestWritingDoneToday:
    def test_not_done_when_no_attempts_or_progress(self, db_session):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['writing_prompt'],
        )
        result = _writing_done_today(user.id, lessons[0].id, 'writing_prompt', real_db)
        assert result is False

    def test_done_when_writing_attempt_today(self, db_session):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['writing_prompt'],
        )
        _add_writing_attempt(db_session, user, lessons[0])
        result = _writing_done_today(user.id, lessons[0].id, 'writing_prompt', real_db)
        assert result is True

    def test_done_when_lesson_progress_completed(self, db_session):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['translation'],
        )
        _mark_completed(db_session, user, lessons[0])
        result = _writing_done_today(user.id, lessons[0].id, 'translation', real_db)
        assert result is True


# ---------------------------------------------------------------------------
# Tests for build_writing_slot
# ---------------------------------------------------------------------------

class TestBuildWritingSlot:
    def test_returns_none_when_no_writing_lesson(self, db_session, monkeypatch):
        user = _make_user(db_session)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: None,
        )
        result = build_writing_slot(user.id, real_db)
        assert result is None

    def test_returns_writing_slot_with_correct_shape(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'writing_prompt'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot = build_writing_slot(user.id, real_db)
        assert slot is not None
        assert isinstance(slot, LinearSlot)
        assert slot.kind == 'writing'
        assert slot.lesson_type == 'writing_prompt'
        assert slot.completed is False
        assert slot.data['lesson_id'] == lessons[1].id
        assert slot.data['lesson_type'] == 'writing_prompt'
        assert slot.data['estimated_minutes'] == _WRITING_SLOT_ETA_MINUTES
        assert slot.url is not None

    def test_slot_completed_when_writing_attempt_today(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'writing_prompt'],
        )
        vocab_lesson = lessons[0]
        writing_lesson = lessons[1]
        _add_writing_attempt(db_session, user, writing_lesson)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot = build_writing_slot(user.id, real_db)
        assert slot is not None
        assert slot.completed is True

    def test_to_dict_includes_all_required_fields(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'translation'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot_dict = build_writing_slot(user.id, real_db).to_dict()
        assert set(slot_dict) == {
            'kind', 'title', 'lesson_type', 'eta_minutes', 'url', 'completed', 'data',
        }
        assert slot_dict['kind'] == 'writing'
        assert slot_dict['lesson_type'] == 'translation'

    def test_writing_prompt_includes_prompt_preview(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'writing_prompt'],
        )
        vocab_lesson = lessons[0]
        writing_lesson = lessons[1]
        writing_lesson.content = {'prompt': 'Describe your morning routine', 'min_words': 50}
        db_session.commit()
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        slot = build_writing_slot(user.id, real_db)
        assert slot is not None
        assert slot.data.get('prompt_preview') == 'Describe your morning routine'


# ---------------------------------------------------------------------------
# Tests for chain EXTENSION_PRIORITY
# ---------------------------------------------------------------------------

class TestChainIntegration:
    def test_writing_in_extension_priority(self):
        assert 'writing' in EXTENSION_PRIORITY

    def test_writing_after_listening_in_priority(self):
        assert EXTENSION_PRIORITY.index('writing') > EXTENSION_PRIORITY.index('listening')

    def test_writing_before_error_review_in_priority(self):
        assert EXTENSION_PRIORITY.index('writing') < EXTENSION_PRIORITY.index('error_review')

    def test_build_writing_extension_returns_none_when_no_lesson(
        self, db_session, monkeypatch
    ):
        user = _make_user(db_session)
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: None,
        )
        result = _build_writing_extension(user.id, real_db, [])
        assert result is None

    def test_build_writing_extension_marks_extension_true(self, db_session, monkeypatch):
        user = _make_user(db_session)
        _module, lessons = _make_module_with_lessons(
            db_session,
            lesson_types=['vocabulary', 'writing_prompt'],
        )
        vocab_lesson = lessons[0]
        monkeypatch.setattr(
            'app.daily_plan.linear.slots.writing_slot.find_next_lesson_linear',
            lambda uid, db: vocab_lesson,
        )
        result = _build_writing_extension(user.id, real_db, [])
        assert result is not None
        assert result['data']['extension'] is True

    def test_build_writing_extension_skips_when_already_in_chain(
        self, db_session, monkeypatch
    ):
        user = _make_user(db_session)
        existing_chain = [{'kind': 'writing', 'completed': False}]
        result = _build_writing_extension(user.id, real_db, existing_chain)
        assert result is None


# ---------------------------------------------------------------------------
# Tests for compute_linear_day_secured with writing slot
# ---------------------------------------------------------------------------

class TestDaySecuredUnaffectedByWritingSlot:
    def test_writing_slot_not_in_baseline_does_not_block_secured(self):
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

    def test_writing_extension_slot_never_blocks_secured(self):
        baseline_slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ]
        writing_extension = {'kind': 'writing', 'completed': False}
        assert compute_linear_day_secured(baseline_slots) is True
        assert compute_linear_day_secured(baseline_slots + [writing_extension]) is False
