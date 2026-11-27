"""Curriculum grammar lessons feed the grammar SRS consumers (finding #5).

Course grammar lessons (type='grammar') write LessonProgress/LessonAttempt, not
UserGrammarExercise. These tests verify the read-time union added to the three
consumers so course grammar is no longer invisible to them:

- _grammar_reviewed_today  → grammar_review slot flips from a course attempt
- _stalest_practiced_topic → surfaces a topic practised only via the course
- _get_weak_grammar_topic_ids → weak hint sees low course-grammar accuracy
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import scoped_session

from app.auth.models import User
from app.curriculum.models import LessonAttempt, Lessons
from app.daily_plan.items.curriculum import _get_weak_grammar_topic_ids
from app.daily_plan.items.grammar_review import (
    _grammar_reviewed_today,
    _stalest_practiced_topic,
    build_grammar_review_item,
)
from app.grammar_lab.models import GrammarExercise, GrammarTopic, UserGrammarExercise
from app.utils.db import db as app_db  # extension (has .session) — what the consumers expect


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def grammar_topic(db_session):
    unique = uuid.uuid4().hex[:8]
    topic = GrammarTopic(
        slug=f'union-{unique}',
        title='Union Topic',
        title_ru='Юнион',
        level='B1',  # must be a public CEFR code for the slot consumers
        order=1,
        content={'introduction': 'x', 'sections': []},
        estimated_time=10,
        difficulty=2,
    )
    db_session.add(topic)
    db_session.commit()
    return topic


@pytest.fixture
def grammar_lesson(db_session, test_module, grammar_topic):
    lesson = Lessons(
        module_id=test_module.id,
        number=7,
        title='Course Grammar',
        type='grammar',
        order=0,
        content={'exercises': []},
        grammar_topic_id=grammar_topic.id,
    )
    db_session.add(lesson)
    db_session.commit()
    return lesson


def _add_attempt(db_session, user_id, lesson_id, *, correct, total, when=None, passed=False):
    attempt = LessonAttempt(
        user_id=user_id,
        lesson_id=lesson_id,
        attempt_number=1,
        completed_at=when or _naive_utc_now(),
        score=round(correct / total * 100, 2) if total else 0,
        passed=passed,
        correct_answers=correct,
        total_questions=total,
    )
    db_session.add(attempt)
    db_session.commit()
    return attempt


class TestGrammarReviewedTodayUnion:
    def test_slot_flips_from_curriculum_attempt(self, db_session, test_user, grammar_lesson):
        """A grammar LessonAttempt today flips the slot — no UserGrammarExercise."""
        assert _grammar_reviewed_today(test_user.id, app_db) is False

        _add_attempt(db_session, test_user.id, grammar_lesson.id, correct=3, total=5)

        assert _grammar_reviewed_today(test_user.id, app_db) is True

    def test_non_grammar_attempt_does_not_flip(self, db_session, test_user, test_lesson_quiz):
        """A non-grammar (quiz) attempt today must NOT flip the grammar slot."""
        _add_attempt(db_session, test_user.id, test_lesson_quiz.id, correct=5, total=5)

        assert _grammar_reviewed_today(test_user.id, app_db) is False


class TestStalestTopicUnion:
    def test_returns_topic_practised_only_via_curriculum(
        self, db_session, test_user, grammar_lesson, grammar_topic
    ):
        """Stalest topic is found from course attempts when no standalone history."""
        assert _stalest_practiced_topic(test_user.id, app_db) is None

        _add_attempt(db_session, test_user.id, grammar_lesson.id, correct=2, total=5)

        topic = _stalest_practiced_topic(test_user.id, app_db)
        assert topic is not None
        assert topic.id == grammar_topic.id

    @pytest.mark.parametrize('source', ['curriculum', 'standalone'])
    def test_optional_history_requires_a_playable_topic(
        self, db_session: scoped_session, test_user: User, grammar_lesson: Lessons, grammar_topic: GrammarTopic,
        source: str,
    ) -> None:
        previous = _naive_utc_now() - timedelta(days=1)
        retired = GrammarExercise(topic_id=grammar_topic.id, exercise_type='fill_blank',
                                  content={'question': 'We ___ here.', 'correct_answer': 'are', 'guided_retired': True})
        db_session.add(retired)
        db_session.flush()
        if source == 'standalone':
            progress = UserGrammarExercise(user_id=test_user.id, exercise_id=retired.id)
            progress.last_reviewed = previous
            db_session.add(progress)
        else:
            _add_attempt(db_session, test_user.id, grammar_lesson.id, correct=2, total=5, when=previous)
        db_session.commit()
        assert build_grammar_review_item(test_user.id, app_db) is None

        db_session.add(GrammarExercise(topic_id=grammar_topic.id, exercise_type='fill_blank',
                                       content={'question': 'He ___ here.', 'correct_answer': 'is'}))
        db_session.commit()
        item = build_grammar_review_item(test_user.id, app_db)
        assert item is not None and item.data['topic_id'] == grammar_topic.id


class TestWeakHintUnion:
    def test_low_curriculum_accuracy_flags_weak(
        self, db_session, test_user, grammar_lesson, grammar_topic
    ):
        """Low course-grammar accuracy marks the topic weak (no standalone rows)."""
        # 1/5 = 0.2 accuracy over total >= min_attempts (3)
        _add_attempt(db_session, test_user.id, grammar_lesson.id, correct=1, total=5)

        weak = _get_weak_grammar_topic_ids(test_user.id, app_db)
        assert grammar_topic.id in weak
        assert abs(weak[grammar_topic.id]['accuracy'] - 0.2) < 0.001

    def test_high_curriculum_accuracy_not_weak(
        self, db_session, test_user, grammar_lesson, grammar_topic
    ):
        """High course-grammar accuracy does not flag the topic."""
        _add_attempt(db_session, test_user.id, grammar_lesson.id, correct=5, total=5)

        weak = _get_weak_grammar_topic_ids(test_user.id, app_db)
        assert grammar_topic.id not in weak

    def test_below_min_attempts_not_weak(
        self, db_session, test_user, grammar_lesson, grammar_topic
    ):
        """Fewer than min_attempts total questions → filtered by HAVING."""
        _add_attempt(db_session, test_user.id, grammar_lesson.id, correct=0, total=2)

        weak = _get_weak_grammar_topic_ids(test_user.id, app_db)
        assert grammar_topic.id not in weak
