"""Tests for linear daily plan XP wiring from slot completions.

Covers the Task 14 integration layer:
- ``maybe_award_curriculum_xp`` gates on ``User.use_linear_plan`` and on
  a recognised lesson type; awards the right source key once per day.
- ``maybe_award_srs_global_xp`` / ``maybe_award_book_reading_xp`` /
  ``maybe_award_error_review_xp`` behave idempotently per day.
- ``maybe_award_linear_perfect_day`` only fires when every baseline
  slot is completed.
- Full linear day (curriculum card + SRS + book + optional perfect-day
  bonus) matches the acceptance target of 43 XP without streak.
- Mission users are unaffected — calling the linear helpers on a
  mission-flag user returns ``None`` and writes no StreakEvents.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.achievements.models import StreakEvent, UserStatistics
from app.achievements.xp_service import (
    PERFECT_DAY_BONUS_XP_LINEAR,
    get_today_xp,
)
from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.xp import (
    LESSON_TYPE_TO_SOURCE,
    LINEAR_XP_EVENT_TYPE,
    award_linear_slot_xp_idempotent,
    get_source_for_lesson_type,
    is_linear_user,
    maybe_award_book_reading_xp,
    maybe_award_curriculum_xp,
    maybe_award_error_review_xp,
    maybe_award_linear_perfect_day,
    maybe_award_srs_global_xp,
)
from app.utils.db import db as real_db


def _make_user(db_session, *, use_linear_plan=True) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'linxp_{suffix}',
        email=f'linxp_{suffix}@example.com',
        active=True,
        use_linear_plan=use_linear_plan,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    db_session.add(UserStatistics(user_id=user.id, total_xp=0, current_streak_days=0))
    db_session.commit()
    return user


def _unique_level_code() -> str:
    # CEFRLevel.code is VARCHAR(2); use a random suffix to avoid colliding
    # with other tests that truncate+recreate levels between runs.
    return uuid.uuid4().hex[:2].upper()


def _ensure_module(db_session) -> Module:
    # Reuse an existing level+module when possible — lesson types are
    # what drive the test assertions, not level/module identity.
    module = db_session.query(Module).order_by(Module.id.asc()).first()
    if module is not None:
        return module
    for _ in range(20):
        code = _unique_level_code()
        if not db_session.query(CEFRLevel).filter_by(code=code).first():
            break
    level = CEFRLevel(code=code, name='L', description='d', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='M',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    return module


def _make_lesson(db_session, lesson_type: str) -> Lessons:
    module = _ensure_module(db_session)
    next_number = (
        db_session.query(Lessons)
        .filter_by(module_id=module.id)
        .count()
    ) + 1
    lesson = Lessons(
        module_id=module.id,
        number=next_number,
        title=f'L-{lesson_type}',
        type=lesson_type,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _streak_events_for(user_id: int) -> list[StreakEvent]:
    return (
        StreakEvent.query.filter_by(user_id=user_id, event_type=LINEAR_XP_EVENT_TYPE)
        .order_by(StreakEvent.id.asc())
        .all()
    )


class TestLessonTypeMapping:
    def test_every_canonical_type_has_a_source(self):
        canonical = {
            'card', 'vocabulary', 'grammar', 'quiz', 'reading',
            'listening_quiz', 'dialogue_completion_quiz', 'ordering_quiz',
            'translation_quiz', 'final_test', 'listening_immersion',
        }
        for lesson_type in canonical:
            assert get_source_for_lesson_type(lesson_type) is not None

    def test_legacy_aliases_map_to_canonical_sources(self):
        assert get_source_for_lesson_type('flashcards') == 'linear_curriculum_card'
        assert get_source_for_lesson_type('text') == 'linear_curriculum_reading'
        assert get_source_for_lesson_type('matching') == 'linear_curriculum_quiz'
        assert (
            get_source_for_lesson_type('listening_immersion_quiz')
            == 'linear_curriculum_listening_immersion'
        )

    def test_unknown_and_missing_types_return_none(self):
        assert get_source_for_lesson_type(None) is None
        assert get_source_for_lesson_type('') is None
        assert get_source_for_lesson_type('totally_unknown') is None


class TestIsLinearUser:
    def test_true_when_flag_enabled(self, db_session):
        user = _make_user(db_session, use_linear_plan=True)
        assert is_linear_user(user.id) is True

    def test_false_when_flag_disabled(self, db_session):
        user = _make_user(db_session, use_linear_plan=False)
        assert is_linear_user(user.id) is False

    def test_false_when_user_missing(self):
        assert is_linear_user(-999_999) is False


class TestAwardLinearSlotXpIdempotent:
    def test_awards_once_per_day_per_source(self, db_session):
        user = _make_user(db_session)
        today = date(2026, 4, 20)

        first = award_linear_slot_xp_idempotent(
            user.id, 'linear_curriculum_card', today, real_db,
        )
        db_session.commit()
        second = award_linear_slot_xp_idempotent(
            user.id, 'linear_curriculum_card', today, real_db,
        )
        db_session.commit()

        assert first is not None and first.xp_awarded == 20
        assert second is None

        events = _streak_events_for(user.id)
        assert len(events) == 1
        assert events[0].details['source'] == 'linear_curriculum_card'
        assert events[0].details['xp'] == 20

    def test_different_sources_award_independently(self, db_session):
        user = _make_user(db_session)
        today = date(2026, 4, 20)

        award_linear_slot_xp_idempotent(user.id, 'linear_curriculum_card', today, real_db)
        award_linear_slot_xp_idempotent(user.id, 'linear_srs_global', today, real_db)
        award_linear_slot_xp_idempotent(user.id, 'linear_book_reading', today, real_db)
        db_session.commit()

        events = _streak_events_for(user.id)
        sources = sorted(ev.details['source'] for ev in events)
        assert sources == [
            'linear_book_reading', 'linear_curriculum_card', 'linear_srs_global',
        ]

    def test_unknown_source_returns_none(self, db_session):
        user = _make_user(db_session)
        result = award_linear_slot_xp_idempotent(
            user.id, 'linear_bogus', date(2026, 4, 20), real_db,
        )
        assert result is None
        assert _streak_events_for(user.id) == []

    def test_different_days_reset_idempotency(self, db_session):
        user = _make_user(db_session)
        d1 = date(2026, 4, 19)
        d2 = date(2026, 4, 20)

        r1 = award_linear_slot_xp_idempotent(user.id, 'linear_srs_global', d1, real_db)
        r2 = award_linear_slot_xp_idempotent(user.id, 'linear_srs_global', d2, real_db)
        db_session.commit()

        assert r1 is not None
        assert r2 is not None
        assert len(_streak_events_for(user.id)) == 2


class TestMaybeAwardCurriculumXp:
    def test_skips_non_linear_user(self, db_session):
        user = _make_user(db_session, use_linear_plan=False)
        lesson = _make_lesson(db_session, 'card')

        result = maybe_award_curriculum_xp(user.id, lesson, db_session=real_db)
        db_session.commit()

        assert result is None
        assert _streak_events_for(user.id) == []

    def test_awards_for_each_canonical_type(self, db_session):
        user = _make_user(db_session)

        # ``listening_immersion`` and ``listening_immersion_quiz`` share a
        # single XP source key, so covering one covers the other for
        # idempotency purposes. The three legacy aliases have dedicated
        # coverage in ``test_legacy_aliases_map_to_canonical_sources``.
        aliased_types = {'flashcards', 'text', 'matching', 'listening_immersion_quiz'}
        for lesson_type, expected_source in LESSON_TYPE_TO_SOURCE.items():
            if lesson_type in aliased_types:
                continue
            lesson = _make_lesson(db_session, lesson_type)
            result = maybe_award_curriculum_xp(user.id, lesson, db_session=real_db)
            db_session.commit()
            assert result is not None, f'no award for {lesson_type}'
            recorded = [
                ev for ev in _streak_events_for(user.id)
                if ev.details.get('source') == expected_source
            ]
            assert recorded, f'missing streak event for {expected_source}'

    def test_idempotent_per_day(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, 'card')

        first = maybe_award_curriculum_xp(user.id, lesson, db_session=real_db)
        db_session.commit()
        second = maybe_award_curriculum_xp(user.id, lesson, db_session=real_db)
        db_session.commit()

        assert first is not None
        assert second is None
        card_events = [
            ev for ev in _streak_events_for(user.id)
            if ev.details['source'] == 'linear_curriculum_card'
        ]
        assert len(card_events) == 1


class TestMaybeAwardSlotHelpers:
    def test_srs_global_xp(self, db_session):
        user = _make_user(db_session)
        result = maybe_award_srs_global_xp(user.id, db_session=real_db)
        db_session.commit()
        assert result is not None
        assert result.xp_awarded == 8

    def test_book_reading_xp(self, db_session):
        user = _make_user(db_session)
        result = maybe_award_book_reading_xp(user.id, db_session=real_db)
        db_session.commit()
        assert result is not None
        assert result.xp_awarded == 15

    def test_error_review_xp(self, db_session):
        user = _make_user(db_session)
        result = maybe_award_error_review_xp(user.id, db_session=real_db)
        db_session.commit()
        assert result is not None
        assert result.xp_awarded == 10

    def test_mission_user_gets_nothing(self, db_session):
        user = _make_user(db_session, use_linear_plan=False)

        assert maybe_award_srs_global_xp(user.id, db_session=real_db) is None
        assert maybe_award_book_reading_xp(user.id, db_session=real_db) is None
        assert maybe_award_error_review_xp(user.id, db_session=real_db) is None
        db_session.commit()
        assert _streak_events_for(user.id) == []


class TestMaybeAwardLinearPerfectDay:
    def _stub_plan(self, baseline_slots):
        return {
            'mode': 'linear',
            'baseline_slots': baseline_slots,
            'continuation': {'available': False, 'next_lessons': []},
            'day_secured': all(s['completed'] for s in baseline_slots),
        }

    def test_awards_when_all_slots_done(self, db_session):
        user = _make_user(db_session)
        stub = self._stub_plan([
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ])
        with patch('app.daily_plan.linear.plan.get_linear_plan', return_value=stub):
            result = maybe_award_linear_perfect_day(user.id, db_session=real_db)
        db_session.commit()

        assert result is not None
        assert result.xp_awarded == PERFECT_DAY_BONUS_XP_LINEAR

    def test_noop_when_slot_incomplete(self, db_session):
        user = _make_user(db_session)
        stub = self._stub_plan([
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': False},
            {'kind': 'reading', 'completed': True},
        ])
        with patch('app.daily_plan.linear.plan.get_linear_plan', return_value=stub):
            result = maybe_award_linear_perfect_day(user.id, db_session=real_db)
        db_session.commit()

        assert result is None
        perfect_events = StreakEvent.query.filter_by(
            user_id=user.id, event_type='xp_perfect_day',
        ).all()
        assert perfect_events == []

    def test_noop_without_baseline_slots(self, db_session):
        user = _make_user(db_session)
        stub = self._stub_plan([])
        with patch('app.daily_plan.linear.plan.get_linear_plan', return_value=stub):
            result = maybe_award_linear_perfect_day(user.id, db_session=real_db)
        db_session.commit()
        assert result is None

    def test_skips_non_linear_user(self, db_session):
        user = _make_user(db_session, use_linear_plan=False)
        stub = self._stub_plan([
            {'kind': 'curriculum', 'completed': True},
            {'kind': 'srs', 'completed': True},
            {'kind': 'reading', 'completed': True},
        ])
        with patch('app.daily_plan.linear.plan.get_linear_plan', return_value=stub):
            result = maybe_award_linear_perfect_day(user.id, db_session=real_db)
        db_session.commit()
        assert result is None

    def test_plan_assembly_failure_does_not_raise(self, db_session):
        user = _make_user(db_session)

        def _boom(*args, **kwargs):
            raise RuntimeError('kaboom')

        with patch('app.daily_plan.linear.plan.get_linear_plan', side_effect=_boom):
            result = maybe_award_linear_perfect_day(user.id, db_session=real_db)
        assert result is None


class TestFullLinearDay:
    def test_baseline_day_xp_is_43_without_streak(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, 'card')

        maybe_award_curriculum_xp(user.id, lesson, db_session=real_db)
        maybe_award_srs_global_xp(user.id, db_session=real_db)
        maybe_award_book_reading_xp(user.id, db_session=real_db)
        db_session.commit()

        stats = UserStatistics.query.filter_by(user_id=user.id).first()
        assert stats.total_xp == 43

    def test_perfect_day_bonus_adds_25(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, 'card')

        maybe_award_curriculum_xp(user.id, lesson, db_session=real_db)
        maybe_award_srs_global_xp(user.id, db_session=real_db)
        maybe_award_book_reading_xp(user.id, db_session=real_db)

        stub = {
            'mode': 'linear',
            'baseline_slots': [
                {'kind': 'curriculum', 'completed': True},
                {'kind': 'srs', 'completed': True},
                {'kind': 'reading', 'completed': True},
            ],
            'day_secured': True,
        }
        with patch('app.daily_plan.linear.plan.get_linear_plan', return_value=stub):
            bonus = maybe_award_linear_perfect_day(user.id, db_session=real_db)
        db_session.commit()

        assert bonus is not None
        stats = UserStatistics.query.filter_by(user_id=user.id).first()
        assert stats.total_xp == 43 + PERFECT_DAY_BONUS_XP_LINEAR  # 68

    def test_get_today_xp_sums_linear_events(self, db_session):
        user = _make_user(db_session)
        today = date(2026, 4, 20)

        award_linear_slot_xp_idempotent(
            user.id, 'linear_curriculum_card', today, real_db,
        )
        award_linear_slot_xp_idempotent(
            user.id, 'linear_srs_global', today, real_db,
        )
        award_linear_slot_xp_idempotent(
            user.id, 'linear_book_reading', today, real_db,
        )
        db_session.commit()

        assert get_today_xp(user.id, today) == 43
        assert get_today_xp(user.id, today - timedelta(days=1)) == 0


class TestMissionUserRegressions:
    def test_mission_user_can_still_award_phase_xp(self, db_session):
        """Linear wiring does not break the mission phase-XP flow."""
        from app.achievements.xp_service import award_phase_xp_idempotent

        user = _make_user(db_session, use_linear_plan=False)
        today = date(2026, 4, 20)

        result = award_phase_xp_idempotent(user.id, 'phase_xyz', 'learn', today)
        db_session.commit()

        assert result is not None
        assert result.xp_awarded == 40
        stats = UserStatistics.query.filter_by(user_id=user.id).first()
        assert stats.total_xp == 40

    def test_linear_helpers_noop_for_mission_user(self, db_session):
        user = _make_user(db_session, use_linear_plan=False)
        lesson = _make_lesson(db_session, 'card')

        assert maybe_award_curriculum_xp(user.id, lesson, db_session=real_db) is None
        assert maybe_award_srs_global_xp(user.id, db_session=real_db) is None
        db_session.commit()

        stats = UserStatistics.query.filter_by(user_id=user.id).first()
        assert stats.total_xp == 0
