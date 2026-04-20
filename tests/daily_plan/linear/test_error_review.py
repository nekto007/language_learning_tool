"""Tests for the linear daily plan error-review slot and logging helpers.

Covers:
- ``log_quiz_error`` / ``log_quiz_errors_from_result`` persist one row per
  incorrect answer with a structured payload.
- ``resolve_quiz_error`` sets ``resolved_at`` and is ownership-safe.
- ``should_show_error_review`` enforces the (5+ unresolved) AND (3+ days
  cooldown or never resolved) trigger.
- ``build_error_review_slot`` returns ``None`` when the trigger is off
  and a ``LinearSlot`` otherwise.
- Each quiz lesson type (``quiz``, ``listening_quiz``,
  ``dialogue_completion_quiz``, ``ordering_quiz``, ``translation_quiz``,
  ``final_test``) produces log rows when submitted with an incorrect
  answer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.errors import (
    REVIEW_TRIGGER_COOLDOWN,
    REVIEW_TRIGGER_MIN_UNRESOLVED,
    count_unresolved,
    get_last_resolved_at,
    get_review_pool,
    log_quiz_error,
    log_quiz_errors_from_result,
    resolve_quiz_error,
    resolve_quiz_errors,
    should_show_error_review,
)
from app.daily_plan.linear.models import QuizErrorLog
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.error_review_slot import build_error_review_slot
from app.utils.db import db as real_db


QUIZ_LESSON_TYPES = [
    'quiz',
    'listening_quiz',
    'dialogue_completion_quiz',
    'ordering_quiz',
    'translation_quiz',
    'final_test',
]


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'erruser_{suffix}',
        email=f'erruser_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_lesson(db_session, lesson_type: str = 'quiz') -> Lessons:
    level = CEFRLevel(code=_unique_code(), name='L', description='desc', order=1)
    db_session.add(level)
    db_session.commit()
    module = Module(
        level_id=level.id,
        number=1,
        title='M1',
        description='d',
        raw_content={'module': {'id': 1}},
    )
    db_session.add(module)
    db_session.commit()
    lesson = Lessons(
        module_id=module.id,
        number=1,
        title=f'Lesson-{lesson_type}',
        type=lesson_type,
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _seed_errors(db_session, user, lesson, count: int, resolved_at=None) -> list[QuizErrorLog]:
    rows: list[QuizErrorLog] = []
    for i in range(count):
        entry = QuizErrorLog(
            user_id=user.id,
            lesson_id=lesson.id,
            question_payload={'seed': i},
            resolved_at=resolved_at,
        )
        db_session.add(entry)
        rows.append(entry)
    db_session.commit()
    return rows


class TestLogQuizError:
    def test_log_single_error_sanitizes_payload(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)

        entry = log_quiz_error(
            user.id,
            lesson.id,
            {'question_text': 'tense?', 'user_answer': 'past'},
            real_db,
            commit=True,
        )

        reloaded = db_session.get(QuizErrorLog, entry.id)
        assert reloaded is not None
        assert reloaded.user_id == user.id
        assert reloaded.lesson_id == lesson.id
        assert reloaded.question_payload['question_text'] == 'tense?'
        assert reloaded.resolved_at is None

    def test_log_non_dict_payload_is_wrapped(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)

        entry = log_quiz_error(user.id, lesson.id, 'some-string', real_db, commit=True)

        reloaded = db_session.get(QuizErrorLog, entry.id)
        assert reloaded.question_payload == {'raw': 'some-string'}

    def test_log_none_payload_sanitized(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)

        entry = log_quiz_error(user.id, lesson.id, None, real_db, commit=True)

        reloaded = db_session.get(QuizErrorLog, entry.id)
        assert reloaded.question_payload == {'raw': ''}


class TestLogQuizErrorsFromResult:
    def test_logs_only_incorrect_entries(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        questions = [
            {'type': 'multiple_choice', 'question': 'Q0', 'options': ['a', 'b']},
            {'type': 'multiple_choice', 'question': 'Q1', 'options': ['a', 'b']},
            {'type': 'multiple_choice', 'question': 'Q2', 'options': ['a', 'b']},
        ]
        result = {
            'feedback': {
                '0': {'status': 'correct', 'user_answer': 'a', 'correct_answer': 'a'},
                '1': {'status': 'incorrect', 'user_answer': 'a', 'correct_answer': 'b'},
                '2': {'status': 'incorrect', 'user_answer': 'a', 'correct_answer': 'b'},
            }
        }

        logged = log_quiz_errors_from_result(user.id, lesson.id, questions, result, real_db)
        db_session.commit()

        assert len(logged) == 2
        stored = (
            db_session.query(QuizErrorLog)
            .filter_by(user_id=user.id, lesson_id=lesson.id)
            .order_by(QuizErrorLog.id.asc())
            .all()
        )
        assert len(stored) == 2
        assert {row.question_payload['question_index'] for row in stored} == {1, 2}
        assert stored[0].question_payload['question_text'] == 'Q1'
        assert stored[0].question_payload['user_answer'] == 'a'
        assert stored[0].question_payload['correct_answer'] == 'b'
        assert stored[0].question_payload['question_type'] == 'multiple_choice'

    def test_missing_or_empty_feedback_noop(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)

        assert log_quiz_errors_from_result(user.id, lesson.id, [], {}, real_db) == []
        assert log_quiz_errors_from_result(user.id, lesson.id, [], {'feedback': {}}, real_db) == []
        assert log_quiz_errors_from_result(user.id, lesson.id, [], {'feedback': None}, real_db) == []
        assert db_session.query(QuizErrorLog).count() == 0

    def test_out_of_range_index_uses_empty_question(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        result = {
            'feedback': {
                '99': {'status': 'incorrect', 'user_answer': 'x', 'correct_answer': 'y'},
            }
        }

        logged = log_quiz_errors_from_result(user.id, lesson.id, [], result, real_db)
        db_session.commit()

        assert len(logged) == 1
        payload = logged[0].question_payload
        assert payload['question_index'] == 99
        assert payload['question_text'] is None
        assert payload['user_answer'] == 'x'


class TestResolveQuizError:
    def test_resolves_own_error(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        entry = _seed_errors(db_session, user, lesson, count=1)[0]

        resolved = resolve_quiz_error(entry.id, user.id, real_db, commit=True)

        assert resolved is not None
        assert resolved.resolved_at is not None
        assert db_session.get(QuizErrorLog, entry.id).resolved_at is not None

    def test_other_users_error_is_noop(self, db_session):
        owner = _make_user(db_session)
        intruder = _make_user(db_session)
        lesson = _make_lesson(db_session)
        entry = _seed_errors(db_session, owner, lesson, count=1)[0]

        result = resolve_quiz_error(entry.id, intruder.id, real_db, commit=True)

        assert result is None
        assert db_session.get(QuizErrorLog, entry.id).resolved_at is None

    def test_missing_error_returns_none(self, db_session):
        user = _make_user(db_session)
        assert resolve_quiz_error(999_999, user.id, real_db) is None

    def test_bulk_resolve_filters_by_ownership(self, db_session):
        owner = _make_user(db_session)
        other = _make_user(db_session)
        lesson = _make_lesson(db_session)
        own = _seed_errors(db_session, owner, lesson, count=2)
        other_entry = _seed_errors(db_session, other, lesson, count=1)[0]

        resolved = resolve_quiz_errors(
            [own[0].id, own[1].id, other_entry.id], owner.id, real_db, commit=True,
        )

        assert len(resolved) == 2
        assert db_session.get(QuizErrorLog, other_entry.id).resolved_at is None


class TestReviewPool:
    def test_returns_oldest_unresolved(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        rows = _seed_errors(db_session, user, lesson, count=3)
        # Mark the first row resolved — pool should return only rows 2 & 3.
        rows[0].resolved_at = datetime.now(timezone.utc)
        db_session.commit()

        pool = get_review_pool(user.id, real_db, limit=10)

        assert len(pool) == 2
        ids = [row.id for row in pool]
        assert ids == [rows[1].id, rows[2].id]

    def test_limit_respected(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=6)

        pool = get_review_pool(user.id, real_db, limit=3)
        assert len(pool) == 3

    def test_zero_limit_returns_empty(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=3)

        assert get_review_pool(user.id, real_db, limit=0) == []


class TestShouldShowErrorReview:
    def test_below_threshold_returns_false(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=REVIEW_TRIGGER_MIN_UNRESOLVED - 1)

        assert should_show_error_review(user.id, real_db) is False

    def test_threshold_without_prior_resolution_triggers(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=REVIEW_TRIGGER_MIN_UNRESOLVED)

        assert should_show_error_review(user.id, real_db) is True

    def test_threshold_but_recent_resolution_suppresses(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=REVIEW_TRIGGER_MIN_UNRESOLVED)
        # A separate resolved row flags the cooldown.
        _seed_errors(
            db_session, user, lesson, count=1,
            resolved_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        assert should_show_error_review(user.id, real_db) is False

    def test_threshold_after_cooldown_triggers(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=REVIEW_TRIGGER_MIN_UNRESOLVED)
        _seed_errors(
            db_session, user, lesson, count=1,
            resolved_at=datetime.now(timezone.utc) - REVIEW_TRIGGER_COOLDOWN - timedelta(hours=1),
        )

        assert should_show_error_review(user.id, real_db) is True

    def test_count_unresolved_and_last_resolved(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        assert count_unresolved(user.id, real_db) == 0
        assert get_last_resolved_at(user.id, real_db) is None

        _seed_errors(db_session, user, lesson, count=3)
        assert count_unresolved(user.id, real_db) == 3

        resolved_at = datetime.now(timezone.utc)
        _seed_errors(db_session, user, lesson, count=1, resolved_at=resolved_at)
        assert count_unresolved(user.id, real_db) == 3

        last = get_last_resolved_at(user.id, real_db)
        assert last is not None


class TestBuildErrorReviewSlot:
    def test_slot_none_below_threshold(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=4)

        assert build_error_review_slot(user.id, real_db) is None

    def test_slot_built_when_triggered(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=7)

        slot = build_error_review_slot(user.id, real_db)

        assert isinstance(slot, LinearSlot)
        assert slot.kind == 'error_review'
        assert slot.title == 'Разбор ошибок (7)'
        assert slot.url == '/learn/error-review?from=linear_plan'
        assert slot.completed is False
        assert slot.data['unresolved_count'] == 7
        assert slot.data['pool_size'] == 7

    def test_slot_pool_size_capped(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=25)

        slot = build_error_review_slot(user.id, real_db)

        assert slot is not None
        assert slot.data['unresolved_count'] == 25
        assert slot.data['pool_size'] == 10

    def test_slot_suppressed_during_cooldown(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=8)
        _seed_errors(
            db_session, user, lesson, count=1,
            resolved_at=datetime.now(timezone.utc),
        )

        assert build_error_review_slot(user.id, real_db) is None


class TestLinearPlanIntegration:
    def test_error_review_absent_by_default(self, db_session):
        from app.daily_plan.linear.plan import get_linear_plan

        user = _make_user(db_session)

        payload = get_linear_plan(user.id, real_db)

        kinds = [s['kind'] for s in payload['baseline_slots']]
        assert 'error_review' not in kinds

    def test_error_review_appended_when_triggered(self, db_session):
        from app.daily_plan.linear.plan import get_linear_plan

        user = _make_user(db_session)
        lesson = _make_lesson(db_session)
        _seed_errors(db_session, user, lesson, count=6)

        payload = get_linear_plan(user.id, real_db)

        error_slot = next(
            (s for s in payload['baseline_slots'] if s['kind'] == 'error_review'),
            None,
        )
        assert error_slot is not None
        assert error_slot['data']['unresolved_count'] == 6


class TestQuizGradingIntegration:
    """Each quiz-type curriculum endpoint that grades answers writes a
    ``QuizErrorLog`` row per incorrect answer.

    We don't spin up the Flask test client here — the grading routes are
    large and couple to session state. Instead we exercise the exact
    ``log_quiz_errors_from_result`` call the routes now make, using the
    real feedback shape ``process_quiz_submission`` produces.
    """

    @pytest.mark.parametrize('lesson_type', QUIZ_LESSON_TYPES)
    def test_log_runs_for_each_lesson_type(self, db_session, lesson_type):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, lesson_type=lesson_type)
        questions = [
            {'type': 'multiple_choice', 'question': f'{lesson_type} q1',
             'options': ['a', 'b']},
        ]
        result = {
            'feedback': {
                '0': {'status': 'incorrect', 'user_answer': 'a', 'correct_answer': 'b'},
            }
        }

        log_quiz_errors_from_result(user.id, lesson.id, questions, result, real_db)
        db_session.commit()

        rows = (
            db_session.query(QuizErrorLog)
            .filter_by(user_id=user.id, lesson_id=lesson.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].question_payload['question_text'] == f'{lesson_type} q1'
