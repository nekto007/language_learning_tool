"""Tests for full linear daily plan assembly and day_secured flow.

Covers:
- ``get_linear_plan`` composes curriculum + SRS + reading + (optional)
  error-review slots and computes ``day_secured`` from slot completion.
- ``continuation.available`` follows ``day_secured``.
- ``compute_linear_day_secured`` ignores empty input and requires every
  slot to be completed.
- ``compute_plan_steps`` returns correct completion and step counts for
  the linear payload (mirroring the mission flow).
- ``write_secured_at`` accepts ``mission_type=None`` for linear plans.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.books.models import Book, Chapter, UserChapterProgress
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.linear.plan import (
    compute_linear_day_secured,
    get_linear_plan,
)
from app.daily_plan.models import DailyPlanLog
from app.daily_plan.service import write_secured_at
from app.achievements.streak_service import compute_plan_steps
from app.study.models import StudySettings, UserCardDirection, UserWord
from app.srs.constants import CardState
from app.utils.db import db as real_db
from app.words.models import CollectionWords


# ── Helpers ──────────────────────────────────────────────────────────


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session, onboarding_level: str | None = None) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'linplan_{suffix}',
        email=f'linplan_{suffix}@example.com',
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


def _record_chapter_progress(
    db_session, user: User, chapter: Chapter, *, offset_pct: float
) -> None:
    db_session.add(UserChapterProgress(
        user_id=user.id,
        chapter_id=chapter.id,
        offset_pct=offset_pct,
        updated_at=datetime.now(timezone.utc),
    ))
    db_session.commit()


def _record_reading_xp_event(db_session, user: User) -> None:
    """Simulate the ``linear_book_reading`` XP award for today.

    The reading slot gates its ``completed`` flag on this event so tests
    that want the slot to appear completed must create one.
    """
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE

    db_session.add(StreakEvent(
        user_id=user.id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=datetime.now(timezone.utc).date(),
        coins_delta=0,
        details={'source': 'linear_book_reading', 'xp': 15},
    ))
    db_session.commit()


def _setup_srs_cards(
    db_session, user: User, *, due: int = 0, studied_today: int = 0
) -> None:
    """Create enough UserCardDirection rows to match the given SRS state."""
    settings = StudySettings.get_settings(user.id)
    settings.new_words_per_day = 10
    db_session.commit()

    now = datetime.now(timezone.utc)
    for _ in range(due):
        word = CollectionWords(
            english_word=f'w_{uuid.uuid4().hex[:6]}',
            russian_word=f'с_{uuid.uuid4().hex[:6]}',
            level='A1',
        )
        db_session.add(word)
        db_session.commit()
        uw = UserWord(user_id=user.id, word_id=word.id)
        db_session.add(uw)
        db_session.commit()
        direction = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
        direction.state = CardState.REVIEW.value
        direction.next_review = now - timedelta(hours=1)
        db_session.add(direction)
        db_session.commit()

    for _ in range(studied_today):
        word = CollectionWords(
            english_word=f'w_{uuid.uuid4().hex[:6]}',
            russian_word=f'с_{uuid.uuid4().hex[:6]}',
            level='A1',
        )
        db_session.add(word)
        db_session.commit()
        uw = UserWord(user_id=user.id, word_id=word.id)
        db_session.add(uw)
        db_session.commit()
        direction = UserCardDirection(user_word_id=uw.id, direction='eng-rus')
        direction.state = CardState.REVIEW.value
        direction.next_review = now + timedelta(days=1)
        direction.last_reviewed = now
        direction.first_reviewed = now
        db_session.add(direction)
        db_session.commit()


@pytest.fixture
def curriculum_setup(db_session):
    level = _make_level(db_session, _unique_code(), order=1)
    module = _make_module(db_session, level, number=1)
    lesson = _make_lesson(db_session, module, number=1, lesson_type='quiz')
    return {'level': level, 'module': module, 'lesson': lesson}


# ── compute_linear_day_secured ───────────────────────────────────────


class TestComputeLinearDaySecured:
    def test_empty_slots_not_secured(self):
        assert compute_linear_day_secured([]) is False

    def test_all_completed_is_secured(self):
        slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ]
        assert compute_linear_day_secured(slots) is True

    def test_any_incomplete_not_secured(self):
        slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': False},
        ]
        assert compute_linear_day_secured(slots) is False

    def test_four_slot_triggered_error_review_required(self):
        slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
            {'kind': 'error_review', 'completed': False},
        ]
        assert compute_linear_day_secured(slots) is False

    def test_four_slots_all_done_is_secured(self):
        slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
            {'kind': 'error_review', 'completed': True},
        ]
        assert compute_linear_day_secured(slots) is True


# ── get_linear_plan assembly ─────────────────────────────────────────


class TestGetLinearPlanAssembly:
    def test_happy_path_three_slots_not_secured(self, db_session, curriculum_setup):
        level = curriculum_setup['level']
        user = _make_user(db_session, onboarding_level=level.code)

        payload = get_linear_plan(user.id, real_db)

        assert payload['mode'] == 'linear'
        kinds = [slot['kind'] for slot in payload['baseline_slots']]
        assert kinds == ['curriculum', 'srs', 'reading']
        assert payload['day_secured'] is False
        assert payload['continuation']['available'] is False
        assert payload['position']['lesson_id'] == curriculum_setup['lesson'].id
        assert payload['progress']['level'] == level.code

    def test_all_three_required_done_secures_day(self, db_session, curriculum_setup):
        level = curriculum_setup['level']
        user = _make_user(db_session, onboarding_level=level.code)
        # Curriculum done: complete the only lesson.
        _complete_lesson(db_session, user, curriculum_setup['lesson'])
        # SRS: nothing due and no activity → slot collapses to completed.
        _setup_srs_cards(db_session, user, due=0, studied_today=0)
        # Reading: preference + XP event (authoritative "read today" signal).
        book = _make_book(db_session)
        _set_reading_preference(db_session, user, book)
        _record_chapter_progress(
            db_session, user, book.chapters[0], offset_pct=0.25,
        )
        _record_reading_xp_event(db_session, user)

        payload = get_linear_plan(user.id, real_db)

        kinds = [slot['kind'] for slot in payload['baseline_slots']]
        assert kinds == ['curriculum', 'srs', 'reading']
        for slot in payload['baseline_slots']:
            assert slot['completed'] is True, f"{slot['kind']} not completed"
        assert payload['day_secured'] is True
        assert payload['continuation']['available'] is True

    def test_fourth_slot_triggered_requires_all_four(self, db_session, curriculum_setup):
        from app.daily_plan.linear.models import QuizErrorLog

        level = curriculum_setup['level']
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, curriculum_setup['lesson'])
        _setup_srs_cards(db_session, user, due=0, studied_today=0)
        book = _make_book(db_session)
        _set_reading_preference(db_session, user, book)
        _record_chapter_progress(
            db_session, user, book.chapters[0], offset_pct=0.25,
        )
        _record_reading_xp_event(db_session, user)
        # Seed 6 unresolved errors → should_show_error_review is True.
        for i in range(6):
            db_session.add(QuizErrorLog(
                user_id=user.id,
                lesson_id=curriculum_setup['lesson'].id,
                question_payload={'i': i},
            ))
        db_session.commit()

        payload = get_linear_plan(user.id, real_db)

        kinds = [slot['kind'] for slot in payload['baseline_slots']]
        assert 'error_review' in kinds
        # First three are completed, but error_review is not — day is not secured.
        assert payload['day_secured'] is False
        assert payload['continuation']['available'] is False

    def test_position_is_none_when_curriculum_complete(self, db_session, curriculum_setup):
        level = curriculum_setup['level']
        user = _make_user(db_session, onboarding_level=level.code)
        _complete_lesson(db_session, user, curriculum_setup['lesson'])

        payload = get_linear_plan(user.id, real_db)

        assert payload['position'] is None
        # Curriculum slot renders as the "complete" empty variant.
        curriculum_slot = next(
            s for s in payload['baseline_slots'] if s['kind'] == 'curriculum'
        )
        assert curriculum_slot['completed'] is True


# ── compute_plan_steps for linear payload ────────────────────────────


class TestComputePlanStepsLinear:
    def _plan(self, baseline_slots):
        return {'mode': 'linear', 'baseline_slots': baseline_slots}

    def test_empty_summary_relies_on_slot_completed(self):
        baseline_slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': False},
            {'kind': 'reading', 'completed': False},
        ]
        summary = {
            'lessons_count': 0,
            'words_reviewed': 0,
            'srs_words_reviewed': 0,
            'srs_review_reviewed': 0,
            'books_read': [],
        }

        plan_completion, steps_available, steps_done, steps_total = compute_plan_steps(
            self._plan(baseline_slots), summary,
        )

        assert plan_completion == {'curriculum': True, 'srs': False, 'reading': False}
        assert steps_available == {'curriculum': True, 'srs': True, 'reading': True}
        assert steps_done == 1
        assert steps_total == 3

    def test_summary_flags_promote_completion(self):
        baseline_slots = [
            {'kind': 'curriculum', 'completed': False},
            {'kind': 'srs', 'completed': False},
            {'kind': 'reading', 'completed': True},
        ]
        summary = {
            'lessons_count': 1,
            'words_reviewed': 5,
            'srs_words_reviewed': 5,
            'srs_review_reviewed': 5,
            'books_read': ['Book X'],
        }

        plan_completion, _, steps_done, steps_total = compute_plan_steps(
            self._plan(baseline_slots), summary,
        )

        # Reading has no summary fallback; it relies on slot.completed
        # (which is gated on the linear_book_reading XP event).
        assert plan_completion == {'curriculum': True, 'srs': True, 'reading': True}
        assert steps_done == 3
        assert steps_total == 3

    def test_reading_summary_signal_does_not_promote_slot(self):
        """``books_read`` alone must not flip the reading slot to complete —
        it does not filter by preferred book nor apply the progress threshold."""
        baseline_slots = [
            {'kind': 'curriculum', 'completed': False},
            {'kind': 'srs', 'completed': False},
            {'kind': 'reading', 'completed': False},
        ]
        summary = {
            'lessons_count': 0,
            'words_reviewed': 0,
            'srs_words_reviewed': 0,
            'srs_review_reviewed': 0,
            'books_read': ['Random Book'],
        }

        plan_completion, _, _, _ = compute_plan_steps(
            self._plan(baseline_slots), summary,
        )
        assert plan_completion['reading'] is False

    def test_four_slot_linear_plan_counts_error_review(self):
        baseline_slots = [
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
            {'kind': 'error_review', 'completed': False},
        ]
        summary = {
            'lessons_count': 1,
            'words_reviewed': 5,
            'srs_words_reviewed': 5,
            'srs_review_reviewed': 5,
            'books_read': ['Book X'],
        }

        plan_completion, steps_available, steps_done, steps_total = compute_plan_steps(
            self._plan(baseline_slots), summary,
        )

        # error_review stays incomplete — no summary signal promotes it.
        assert plan_completion['error_review'] is False
        assert steps_total == 4
        assert steps_done == 3
        assert set(steps_available.keys()) == {
            'curriculum', 'srs', 'reading', 'error_review',
        }

    def test_empty_baseline_slots_falls_through_to_legacy(self):
        """If mode is not linear and there are no baseline_slots, the
        function falls through to the legacy branch (no exception)."""
        plan = {
            'mode': 'mission',
            'has_any_words': False,
            'next_lesson': None,
            'grammar_topic': None,
            'words_due': 0,
            'book_to_read': None,
        }
        summary = {
            'lessons_count': 0,
            'grammar_exercises': 0,
            'words_reviewed': 0,
            'srs_words_reviewed': 0,
            'books_read': [],
            'book_course_lessons_today': 0,
        }

        # Should not raise even though baseline_slots is missing.
        compute_plan_steps(plan, summary)


# ── write_secured_at handles mission_type=None ───────────────────────


class TestWriteSecuredAtLinear:
    def test_creates_row_with_null_mission_type(self, db_session):
        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()

        write_secured_at(user.id, today, mission_type=None)
        real_db.session.commit()

        log = (
            db_session.query(DailyPlanLog)
            .filter_by(user_id=user.id, plan_date=today)
            .one()
        )
        assert log.mission_type is None
        assert log.secured_at is not None

    def test_idempotent_when_called_twice(self, db_session):
        user = _make_user(db_session)
        today = datetime.now(timezone.utc).date()

        write_secured_at(user.id, today, mission_type=None)
        real_db.session.commit()
        first_secured_at = db_session.query(DailyPlanLog).filter_by(
            user_id=user.id, plan_date=today,
        ).one().secured_at

        write_secured_at(user.id, today, mission_type=None)
        real_db.session.commit()
        second_secured_at = db_session.query(DailyPlanLog).filter_by(
            user_id=user.id, plan_date=today,
        ).one().secured_at

        assert first_secured_at == second_secured_at
