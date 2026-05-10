"""Tests for the linear daily plan slot chain generator (`chain.py`).

Covers:
- `build_next_slot` priority order (curriculum → srs → reading → error_review)
- `build_chain` returns baseline only when baseline isn't fully completed
- `build_chain` extends past the baseline once all baseline slots are done
- exhausted sources are skipped and reported
- chain stops growing when curriculum spine is finished and no other
  source has pending work
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.chain import (
    EXTENSION_PRIORITY,
    build_chain,
    build_next_slot,
)
from app.daily_plan.linear.models import UserReadingPreference
from app.books.models import Book, Chapter
from app.utils.db import db as real_db


# ── Helpers ──────────────────────────────────────────────────────────


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session, onboarding_level: str | None = None) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'chain_{suffix}',
        email=f'chain_{suffix}@example.com',
        active=True,
        onboarding_level=onboarding_level,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_level(db_session, code: str, order: int = 1) -> CEFRLevel:
    level = CEFRLevel(
        code=code,
        name=f'Level {code}',
        description='desc',
        order=order,
    )
    db_session.add(level)
    db_session.commit()
    return level


def _make_module(db_session, level: CEFRLevel, number: int = 1) -> Module:
    module = Module(
        level_id=level.id,
        number=number,
        title=f'{level.code} M{number}',
        description='desc',
        raw_content={},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(
    db_session, module: Module, number: int = 1, lesson_type: str = 'quiz'
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


def _complete_lesson(db_session, user: User, lesson: Lessons) -> None:
    db_session.add(LessonProgress(
        user_id=user.id,
        lesson_id=lesson.id,
        status='completed',
        score=100.0,
        completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    db_session.commit()


def _record_curriculum_xp_event(db_session, user: User, source: str = 'linear_curriculum_quiz') -> None:
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date

    db_session.add(StreakEvent(
        user_id=user.id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=get_linear_event_local_date(user.id, real_db),
        coins_delta=0,
        details={'source': source, 'xp': 10},
    ))
    db_session.commit()


def _record_reading_xp_event(db_session, user: User) -> None:
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date

    db_session.add(StreakEvent(
        user_id=user.id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=get_linear_event_local_date(user.id, real_db),
        coins_delta=0,
        details={'source': 'linear_book_reading', 'xp': 15},
    ))
    db_session.commit()


def _make_book(db_session, *, level: str = 'A2', chapters: int = 2) -> Book:
    suffix = uuid.uuid4().hex[:8]
    book = Book(
        title=f'Book {suffix}',
        author='Author',
        level=level,
        chapters_cnt=chapters,
        summary='s',
    )
    db_session.add(book)
    db_session.commit()
    for chap_num in range(1, chapters + 1):
        db_session.add(Chapter(
            book_id=book.id,
            chap_num=chap_num,
            title=f'Ch {chap_num}',
            words=100,
            text_raw='t',
        ))
    db_session.commit()
    return book


def _set_reading_preference(db_session, user: User, book: Book) -> None:
    db_session.add(UserReadingPreference(
        user_id=user.id,
        book_id=book.id,
        selected_at=datetime.now(timezone.utc),
    ))
    db_session.commit()


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def two_lessons_setup(db_session):
    """A level with two lessons on the spine and a user pinned to that level."""
    level = _make_level(db_session, _unique_code(), order=1)
    module = _make_module(db_session, level, number=1)
    lesson_1 = _make_lesson(db_session, module, number=1, lesson_type='quiz')
    lesson_2 = _make_lesson(db_session, module, number=2, lesson_type='grammar')
    user = _make_user(db_session, onboarding_level=level.code)
    return {
        'level': level,
        'module': module,
        'lesson_1': lesson_1,
        'lesson_2': lesson_2,
        'user': user,
    }


def _mark_baseline_completed(db_session, user: User, lesson: Lessons, book: Book) -> None:
    """Drive baseline curriculum/srs/reading slots all to completed=True."""
    _complete_lesson(db_session, user, lesson)
    # Reading: preference + XP gate event.
    _set_reading_preference(db_session, user, book)
    _record_reading_xp_event(db_session, user)
    # SRS slot collapses to completed when nothing is due and nothing
    # was studied today — no extra setup needed.


# ── EXTENSION_PRIORITY sanity ────────────────────────────────────────


class TestExtensionPriority:
    def test_priority_order_is_stable(self):
        assert EXTENSION_PRIORITY == ('curriculum', 'srs', 'reading', 'listening', 'error_review')


# ── build_chain: baseline-only paths ─────────────────────────────────


class TestBuildChainBaselineOnly:
    def test_empty_activity_returns_baseline_only(self, two_lessons_setup):
        user = two_lessons_setup['user']

        result = build_chain(user.id, real_db)

        kinds = [s['kind'] for s in result['slots']]
        assert kinds == ['curriculum', 'srs', 'reading']
        assert result['baseline_count'] == 3
        # Baseline isn't completed → has_more_available stays True (a
        # future request after completion can grow the chain).
        assert result['has_more_available'] is True
        # No extras were attempted, so no exhausted-sources reported.
        assert result['exhausted_sources'] == []

    def test_partial_baseline_completion_does_not_extend(
        self, two_lessons_setup, db_session
    ):
        """Only curriculum done — chain still equals baseline (no extras)."""
        user = two_lessons_setup['user']
        lesson_1 = two_lessons_setup['lesson_1']
        _complete_lesson(db_session, user, lesson_1)
        _record_curriculum_xp_event(db_session, user)

        result = build_chain(user.id, real_db)

        # No reading preference + reading slot still pending → stop.
        kinds = [s['kind'] for s in result['slots']]
        assert kinds == ['curriculum', 'srs', 'reading']
        assert len(result['slots']) == result['baseline_count']


# ── build_chain: extension paths ─────────────────────────────────────


class TestBuildChainExtensions:
    def test_full_baseline_appends_one_curriculum_extension(
        self, two_lessons_setup, db_session
    ):
        """All baseline slots completed → one extra curriculum slot appended.

        After the user completes lesson_1 today, find_next_lesson_linear
        returns lesson_2, which becomes the chain's 4th slot.
        """
        user = two_lessons_setup['user']
        lesson_1 = two_lessons_setup['lesson_1']
        lesson_2 = two_lessons_setup['lesson_2']
        book = _make_book(db_session)
        _mark_baseline_completed(db_session, user, lesson_1, book)
        _record_curriculum_xp_event(db_session, user)

        result = build_chain(user.id, real_db)

        assert result['baseline_count'] == 3
        assert len(result['slots']) == 4
        last = result['slots'][-1]
        assert last['kind'] == 'curriculum'
        assert last['completed'] is False
        assert last['data']['lesson_id'] == lesson_2.id
        assert last['data'].get('extension') is True
        # has_more_available stays True since the new slot still has work.
        assert result['has_more_available'] is True
        # The curriculum source has a pending extension in the chain — it
        # must NOT be reported as exhausted (regression for the bug where
        # the post-loop builder re-invocation mislabeled pending sources).
        assert 'curriculum' not in result['exhausted_sources']

    def test_max_extra_caps_chain_growth(self, two_lessons_setup, db_session):
        """``max_extra=0`` disables extensions even with completed baseline."""
        user = two_lessons_setup['user']
        lesson_1 = two_lessons_setup['lesson_1']
        book = _make_book(db_session)
        _mark_baseline_completed(db_session, user, lesson_1, book)
        _record_curriculum_xp_event(db_session, user)

        result = build_chain(user.id, real_db, max_extra=0)

        # No extras allowed → chain ≡ baseline.
        assert len(result['slots']) == result['baseline_count']

    def test_curriculum_finished_without_other_sources_ends_chain(
        self, db_session
    ):
        """Course done, no reading prefs, no SRS, no errors → no extras."""
        level = _make_level(db_session, _unique_code(), order=1)
        module = _make_module(db_session, level, number=1)
        lesson = _make_lesson(db_session, module, number=1, lesson_type='quiz')
        user = _make_user(db_session, onboarding_level=level.code)
        # Complete the only lesson on the spine.
        _complete_lesson(db_session, user, lesson)
        _record_curriculum_xp_event(db_session, user)
        # Reading: set preference + XP gate so the slot reads as completed.
        book = _make_book(db_session)
        _set_reading_preference(db_session, user, book)
        _record_reading_xp_event(db_session, user)

        result = build_chain(user.id, real_db)

        # Baseline all completed, but no extension can be supplied:
        # - curriculum spine is finished
        # - SRS has no due cards / no remaining budget
        # - reading already earned XP today
        # - no quiz errors → error_review is not triggered
        assert len(result['slots']) == result['baseline_count']
        assert result['has_more_available'] is False
        # All four sources should appear in the exhausted list.
        assert set(result['exhausted_sources']) == set(EXTENSION_PRIORITY)


# ── build_next_slot: direct unit tests ───────────────────────────────


class TestBuildNextSlot:
    def test_returns_none_when_no_sources_have_work(self, db_session):
        level = _make_level(db_session, _unique_code(), order=1)
        module = _make_module(db_session, level, number=1)
        lesson = _make_lesson(db_session, module, number=1, lesson_type='quiz')
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, lesson)
        _record_curriculum_xp_event(db_session, user)
        book = _make_book(db_session)
        _set_reading_preference(db_session, user, book)
        _record_reading_xp_event(db_session, user)

        # Pretend the entire baseline is in the chain and completed.
        chain = [
            {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': lesson.id}},
            {'kind': 'srs', 'completed': True, 'data': {}},
            {'kind': 'reading', 'completed': True, 'data': {}},
        ]

        assert build_next_slot(user.id, real_db, chain) is None

    def test_picks_curriculum_when_pending(self, two_lessons_setup, db_session):
        user = two_lessons_setup['user']
        lesson_1 = two_lessons_setup['lesson_1']
        lesson_2 = two_lessons_setup['lesson_2']
        book = _make_book(db_session)
        _mark_baseline_completed(db_session, user, lesson_1, book)
        _record_curriculum_xp_event(db_session, user)

        # Baseline-shaped chain (curriculum points at lesson_1, completed).
        chain = [
            {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': lesson_1.id}},
            {'kind': 'srs', 'completed': True, 'data': {}},
            {'kind': 'reading', 'completed': True, 'data': {}},
        ]

        slot = build_next_slot(user.id, real_db, chain)
        assert slot is not None
        assert slot['kind'] == 'curriculum'
        assert slot['data']['lesson_id'] == lesson_2.id
        assert slot['data'].get('extension') is True

    def test_skips_curriculum_already_in_chain(
        self, two_lessons_setup, db_session
    ):
        """Once both curriculum lessons are represented in chain, skip curriculum source.

        With no reading preference, no SRS, no errors → no other source
        can fill in either, so build_next_slot returns None.
        """
        user = two_lessons_setup['user']
        lesson_1 = two_lessons_setup['lesson_1']
        lesson_2 = two_lessons_setup['lesson_2']
        # Both lessons completed → spine is empty.
        _complete_lesson(db_session, user, lesson_1)
        _complete_lesson(db_session, user, lesson_2)
        _record_curriculum_xp_event(db_session, user)

        chain = [
            {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': lesson_1.id}},
            {'kind': 'srs', 'completed': True, 'data': {}},
            {'kind': 'reading', 'completed': True, 'data': {}},
            {'kind': 'curriculum', 'completed': True, 'data': {'lesson_id': lesson_2.id}},
        ]

        assert build_next_slot(user.id, real_db, chain) is None
