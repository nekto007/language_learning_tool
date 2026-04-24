"""Tests for grammar-submission error logging into QuizErrorLog."""
from __future__ import annotations

import uuid

from app.auth.models import User
from app.curriculum.grading import process_grammar_submission
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.errors import (
    count_unresolved,
    log_quiz_errors_from_result,
    resolve_quiz_error,
    should_show_error_review,
)
from app.daily_plan.linear.models import QuizErrorLog
from app.utils.db import db as real_db


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'grammar_err_{suffix}',
        email=f'grammar_err_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_grammar_lesson(db_session) -> Lessons:
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
        title='Grammar L',
        type='grammar',
        content={},
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def test_grammar_submission_logs_two_incorrect_rows(db_session):
    user = _make_user(db_session)
    lesson = _make_grammar_lesson(db_session)

    exercises = [
        {'type': 'fill_in_blank', 'prompt': 'I ___ a book.', 'answer': 'read'},
        {'type': 'fill_in_blank', 'prompt': 'She ___ happy.', 'answer': 'is'},
        {'type': 'fill_in_blank', 'prompt': 'We ___ tired.', 'answer': 'are'},
    ]
    answers = {0: 'read', 1: 'was', 2: 'am'}

    result = process_grammar_submission(exercises, answers)
    log_quiz_errors_from_result(user.id, lesson.id, exercises, result, real_db, source='grammar')
    db_session.commit()

    rows = (
        db_session.query(QuizErrorLog)
        .filter_by(user_id=user.id, lesson_id=lesson.id)
        .order_by(QuizErrorLog.id.asc())
        .all()
    )
    assert len(rows) == 2
    indices = {row.question_payload['question_index'] for row in rows}
    assert indices == {1, 2}
    for row in rows:
        assert row.question_payload['source'] == 'grammar'
        assert row.question_payload['question_text'] is not None


def test_grammar_rerun_dedup_same_question(db_session):
    user = _make_user(db_session)
    lesson = _make_grammar_lesson(db_session)

    exercises = [{'type': 'fill_in_blank', 'prompt': 'Q1', 'answer': 'x'}]
    answers = {0: 'wrong'}

    result = process_grammar_submission(exercises, answers)
    log_quiz_errors_from_result(user.id, lesson.id, exercises, result, real_db, source='grammar')
    db_session.commit()

    # Re-attempt with same wrong answer — no second row.
    result2 = process_grammar_submission(exercises, answers)
    log_quiz_errors_from_result(user.id, lesson.id, exercises, result2, real_db, source='grammar')
    db_session.commit()

    rows = (
        db_session.query(QuizErrorLog)
        .filter_by(user_id=user.id, lesson_id=lesson.id)
        .all()
    )
    assert len(rows) == 1


def test_grammar_errors_feed_should_show_error_review(db_session):
    user = _make_user(db_session)
    lesson = _make_grammar_lesson(db_session)

    exercises = [
        {'type': 'fill_in_blank', 'prompt': f'Q{i}', 'answer': 'right'}
        for i in range(5)
    ]
    answers = {i: 'wrong' for i in range(5)}

    result = process_grammar_submission(exercises, answers)
    log_quiz_errors_from_result(user.id, lesson.id, exercises, result, real_db, source='grammar')
    db_session.commit()

    assert count_unresolved(user.id, real_db) == 5
    assert should_show_error_review(user.id, real_db) is True


def test_grammar_error_can_be_resolved(db_session):
    user = _make_user(db_session)
    lesson = _make_grammar_lesson(db_session)

    exercises = [{'type': 'fill_in_blank', 'prompt': 'Q0', 'answer': 'y'}]
    answers = {0: 'wrong'}
    result = process_grammar_submission(exercises, answers)
    logged = log_quiz_errors_from_result(
        user.id, lesson.id, exercises, result, real_db, source='grammar',
    )
    db_session.commit()

    assert len(logged) == 1
    entry = resolve_quiz_error(logged[0].id, user.id, real_db, commit=True)
    assert entry is not None
    assert entry.resolved_at is not None
