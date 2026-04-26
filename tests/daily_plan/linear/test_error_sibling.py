"""Tests for sibling-exercise lookup in the error-review pool.

When the linear plan surfaces a logged quiz error, ``get_review_pool_with_siblings``
attempts to attach a related ``GrammarExercise`` from the same topic so the
review session reinforces the skill instead of re-asking the same memorised
question.
"""
from __future__ import annotations

import uuid

import pytest

from app.auth.models import User
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.daily_plan.linear.errors import (
    get_review_pool_with_siblings,
    get_sibling_exercise,
    log_quiz_errors_from_result,
)
from app.daily_plan.linear.models import QuizErrorLog
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.utils.db import db as real_db


def _unique_code() -> str:
    return uuid.uuid4().hex[:2].upper()


def _make_user(db_session) -> User:
    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f'sibuser_{suffix}',
        email=f'sibuser_{suffix}@example.com',
        active=True,
    )
    user.set_password('secret123')
    db_session.add(user)
    db_session.commit()
    return user


def _make_topic(db_session) -> GrammarTopic:
    topic = GrammarTopic(
        slug=f'topic-{uuid.uuid4().hex[:8]}',
        title='Topic',
        title_ru='Тема',
        level='A1',
    )
    db_session.add(topic)
    db_session.flush()
    return topic


def _make_lesson(db_session, *, grammar_topic_id=None, lesson_type='quiz') -> Lessons:
    level = CEFRLevel(code=_unique_code(), name='L', description='d', order=1)
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
        grammar_topic_id=grammar_topic_id,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _make_exercise(db_session, topic_id: int, *, difficulty: int = 1) -> GrammarExercise:
    ex = GrammarExercise(
        topic_id=topic_id,
        exercise_type='fill_blank',
        content={'question': 'Q __.', 'correct_answer': 'a'},
        difficulty=difficulty,
    )
    db_session.add(ex)
    db_session.flush()
    return ex


def _log_error(db_session, user_id, lesson_id, *, exercise_id=None, difficulty=None) -> QuizErrorLog:
    payload = {'question_index': 0, 'question_text': 'q'}
    if exercise_id is not None:
        payload['exercise_id'] = exercise_id
    if difficulty is not None:
        payload['difficulty'] = difficulty
    row = QuizErrorLog(
        user_id=user_id,
        lesson_id=lesson_id,
        question_payload=payload,
    )
    db_session.add(row)
    db_session.commit()
    return row


class TestSiblingLookup:
    def test_grammar_lesson_returns_sibling_from_same_topic(self, db_session):
        user = _make_user(db_session)
        topic = _make_topic(db_session)
        original = _make_exercise(db_session, topic.id, difficulty=1)
        sibling_target = _make_exercise(db_session, topic.id, difficulty=1)
        db_session.commit()

        lesson = _make_lesson(db_session, grammar_topic_id=topic.id)
        error = _log_error(
            db_session,
            user.id,
            lesson.id,
            exercise_id=original.id,
            difficulty=1,
        )

        sibling = get_sibling_exercise(error, real_db)
        assert sibling is not None
        assert sibling.id == sibling_target.id
        assert sibling.id != original.id

    def test_vocab_lesson_without_grammar_topic_returns_none(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, grammar_topic_id=None)
        error = _log_error(db_session, user.id, lesson.id)

        assert get_sibling_exercise(error, real_db) is None

    def test_no_other_exercise_returns_none(self, db_session):
        user = _make_user(db_session)
        topic = _make_topic(db_session)
        only = _make_exercise(db_session, topic.id, difficulty=1)
        db_session.commit()

        lesson = _make_lesson(db_session, grammar_topic_id=topic.id)
        error = _log_error(
            db_session,
            user.id,
            lesson.id,
            exercise_id=only.id,
            difficulty=1,
        )

        assert get_sibling_exercise(error, real_db) is None

    def test_difficulty_filter_excludes_other_difficulties(self, db_session):
        user = _make_user(db_session)
        topic = _make_topic(db_session)
        original = _make_exercise(db_session, topic.id, difficulty=1)
        # Only sibling has different difficulty.
        _make_exercise(db_session, topic.id, difficulty=3)
        db_session.commit()

        lesson = _make_lesson(db_session, grammar_topic_id=topic.id)
        error = _log_error(
            db_session,
            user.id,
            lesson.id,
            exercise_id=original.id,
            difficulty=1,
        )

        assert get_sibling_exercise(error, real_db) is None


class TestReviewPoolWithSiblings:
    def test_grammar_error_includes_sibling(self, db_session):
        user = _make_user(db_session)
        topic = _make_topic(db_session)
        original = _make_exercise(db_session, topic.id, difficulty=1)
        sib = _make_exercise(db_session, topic.id, difficulty=1)
        db_session.commit()

        lesson = _make_lesson(db_session, grammar_topic_id=topic.id)
        _log_error(db_session, user.id, lesson.id,
                   exercise_id=original.id, difficulty=1)

        items = get_review_pool_with_siblings(user.id, real_db, limit=10)
        assert len(items) == 1
        assert items[0]['error'].lesson_id == lesson.id
        assert items[0]['sibling'] is not None
        assert items[0]['sibling'].id == sib.id

    def test_vocab_error_has_no_sibling(self, db_session):
        user = _make_user(db_session)
        lesson = _make_lesson(db_session, grammar_topic_id=None)
        _log_error(db_session, user.id, lesson.id)

        items = get_review_pool_with_siblings(user.id, real_db, limit=10)
        assert len(items) == 1
        assert items[0]['sibling'] is None

    def test_topic_not_duplicated_across_errors(self, db_session):
        user = _make_user(db_session)
        topic = _make_topic(db_session)
        original = _make_exercise(db_session, topic.id, difficulty=1)
        _make_exercise(db_session, topic.id, difficulty=1)
        db_session.commit()

        lesson = _make_lesson(db_session, grammar_topic_id=topic.id)
        _log_error(db_session, user.id, lesson.id,
                   exercise_id=original.id, difficulty=1)
        # Second error on the same topic.
        row2 = QuizErrorLog(
            user_id=user.id,
            lesson_id=lesson.id,
            question_payload={
                'question_index': 1,
                'exercise_id': original.id,
                'difficulty': 1,
            },
        )
        db_session.add(row2)
        db_session.commit()

        items = get_review_pool_with_siblings(user.id, real_db, limit=10)
        assert len(items) == 2
        siblings = [it['sibling'] for it in items]
        # Only first error gets a sibling — second error of the same topic does not.
        assert siblings[0] is not None
        assert siblings[1] is None


class TestPayloadPersistsExerciseId:
    def test_log_from_result_stores_exercise_id_and_difficulty(self, db_session):
        user = _make_user(db_session)
        topic = _make_topic(db_session)
        ex = _make_exercise(db_session, topic.id, difficulty=2)
        db_session.commit()

        lesson = _make_lesson(db_session, grammar_topic_id=topic.id)
        questions = [
            {
                'id': ex.id,
                'difficulty': 2,
                'question': 'Q',
                'type': 'fill_blank',
            },
        ]
        result = {
            'feedback': {
                '0': {
                    'status': 'incorrect',
                    'user_answer': 'wrong',
                    'correct_answer': 'right',
                },
            },
        }
        logged = log_quiz_errors_from_result(
            user.id, lesson.id, questions, result, real_db, source='grammar',
        )
        db_session.commit()

        assert len(logged) == 1
        payload = logged[0].question_payload
        assert payload['exercise_id'] == ex.id
        assert payload['difficulty'] == 2
