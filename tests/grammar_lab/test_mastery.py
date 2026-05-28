"""
Tests for grammar mastery threshold (30 days) and difficulty-based initial ease.

Covers Task 6 of the learning-quality audit:
- UserGrammarExercise.MASTERED_THRESHOLD_DAYS == 30
- is_mastered honors the per-class threshold (not module-level 180)
- check_and_update_mastery transitions topic to mastered at the new threshold
- compute_initial_ease_for_difficulty maps difficulty 1/2/3 to descending ease
- get_or_create seeds ease_factor based on GrammarExercise.difficulty
"""
import uuid
import pytest

from app.grammar_lab.models import (
    GrammarTopic,
    GrammarExercise,
    UserGrammarExercise,
    UserGrammarTopicStatus,
    compute_initial_ease_for_difficulty,
)
from app.grammar_lab.services.grammar_lab_service import GrammarLabService
from app.srs.constants import CardState, DEFAULT_EASE_FACTOR, MIN_EASE_FACTOR


@pytest.fixture
def topic(db_session):
    unique = uuid.uuid4().hex[:8]
    t = GrammarTopic(
        slug=f'mastery-{unique}',
        title='Mastery Topic',
        title_ru='Тема',
        level='B1',
        order=1,
        content={'introduction': 'Test', 'sections': []},
        estimated_time=10,
        difficulty=2,
    )
    db_session.add(t)
    db_session.commit()
    return t


@pytest.fixture
def exercise_d1(db_session, topic):
    ex = GrammarExercise(
        topic_id=topic.id,
        exercise_type='fill_blank',
        content={'question': 'q ___', 'correct_answer': 'a'},
        difficulty=1,
    )
    db_session.add(ex)
    db_session.commit()
    return ex


@pytest.fixture
def exercise_d3(db_session, topic):
    ex = GrammarExercise(
        topic_id=topic.id,
        exercise_type='fill_blank',
        content={'question': 'q ___', 'correct_answer': 'a'},
        difficulty=3,
    )
    db_session.add(ex)
    db_session.commit()
    return ex


class TestMasteredThreshold:
    def test_threshold_is_30_days(self):
        assert UserGrammarExercise.MASTERED_THRESHOLD_DAYS == 30

    def test_is_mastered_at_30_days(self, db_session, test_user, exercise_d1):
        progress = UserGrammarExercise.get_or_create(test_user.id, exercise_d1.id)
        progress.state = CardState.REVIEW.value
        progress.interval = 30
        db_session.commit()
        assert progress.is_mastered is True

    def test_not_mastered_at_29_days(self, db_session, test_user, exercise_d1):
        progress = UserGrammarExercise.get_or_create(test_user.id, exercise_d1.id)
        progress.state = CardState.REVIEW.value
        progress.interval = 29
        db_session.commit()
        assert progress.is_mastered is False

    def test_classify_returns_mastered_at_threshold(self, db_session, test_user, exercise_d1):
        progress = UserGrammarExercise.get_or_create(test_user.id, exercise_d1.id)
        progress.state = CardState.REVIEW.value
        progress.interval = 30
        db_session.commit()
        assert progress.classify() == 'mastered'


class TestTopicMasteryTransition:
    def test_all_exercises_mastered_promotes_topic(self, db_session, test_user, topic):
        exercises = []
        for i in range(3):
            ex = GrammarExercise(
                topic_id=topic.id,
                exercise_type='fill_blank',
                content={'question': f'q{i} ___', 'correct_answer': 'a'},
                difficulty=1,
            )
            db_session.add(ex)
            exercises.append(ex)
        db_session.commit()

        status = UserGrammarTopicStatus.get_or_create(test_user.id, topic.id)
        status.status = 'practicing'
        for ex in exercises:
            p = UserGrammarExercise.get_or_create(test_user.id, ex.id)
            p.state = CardState.REVIEW.value
            p.interval = 30
        db_session.commit()

        service = GrammarLabService()
        promoted = service.check_and_update_mastery(topic.id, test_user.id)
        assert promoted is True
        assert status.status == 'mastered'

    def test_one_below_threshold_keeps_practicing(self, db_session, test_user, topic):
        ex_a = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'question': 'qa ___', 'correct_answer': 'a'},
            difficulty=1,
        )
        ex_b = GrammarExercise(
            topic_id=topic.id,
            exercise_type='fill_blank',
            content={'question': 'qb ___', 'correct_answer': 'a'},
            difficulty=1,
        )
        db_session.add_all([ex_a, ex_b])
        db_session.commit()

        status = UserGrammarTopicStatus.get_or_create(test_user.id, topic.id)
        status.status = 'practicing'
        pa = UserGrammarExercise.get_or_create(test_user.id, ex_a.id)
        pa.state = CardState.REVIEW.value
        pa.interval = 30
        pb = UserGrammarExercise.get_or_create(test_user.id, ex_b.id)
        pb.state = CardState.REVIEW.value
        pb.interval = 29
        db_session.commit()

        service = GrammarLabService()
        promoted = service.check_and_update_mastery(topic.id, test_user.id)
        assert promoted is False
        assert status.status == 'practicing'


class TestInitialEaseForDifficulty:
    def test_difficulty_none_returns_default(self):
        assert compute_initial_ease_for_difficulty(None) == DEFAULT_EASE_FACTOR

    def test_easiest_int_difficulty_above_default(self):
        ease = compute_initial_ease_for_difficulty(1)
        assert ease > DEFAULT_EASE_FACTOR

    def test_hardest_int_difficulty_below_default(self):
        ease = compute_initial_ease_for_difficulty(3)
        assert ease < DEFAULT_EASE_FACTOR
        assert ease >= MIN_EASE_FACTOR

    def test_normalized_float_above_half_below_default(self):
        # difficulty=0.8 (already normalized) → ease < default
        ease = compute_initial_ease_for_difficulty(0.8)
        assert ease < DEFAULT_EASE_FACTOR

    def test_monotonic_decreasing_across_int_difficulty(self):
        ease1 = compute_initial_ease_for_difficulty(1)
        ease2 = compute_initial_ease_for_difficulty(2)
        ease3 = compute_initial_ease_for_difficulty(3)
        assert ease1 > ease2 > ease3

    def test_clamps_to_min(self):
        ease = compute_initial_ease_for_difficulty(99)
        assert ease >= MIN_EASE_FACTOR

    def test_float_1_0_does_not_go_below_min_ease(self):
        # difficulty=1.0 as a float follows the normalized path (not int branch)
        ease = compute_initial_ease_for_difficulty(1.0)
        assert ease >= MIN_EASE_FACTOR


class TestGetOrCreateSeedsEase:
    def test_easy_exercise_seeds_higher_ease(self, db_session, test_user, exercise_d1):
        progress = UserGrammarExercise.get_or_create(test_user.id, exercise_d1.id)
        assert progress.ease_factor > DEFAULT_EASE_FACTOR

    def test_hard_exercise_seeds_lower_ease(self, db_session, test_user, exercise_d3):
        progress = UserGrammarExercise.get_or_create(test_user.id, exercise_d3.id)
        assert progress.ease_factor < DEFAULT_EASE_FACTOR

    def test_existing_progress_not_reset(self, db_session, test_user, exercise_d3):
        first = UserGrammarExercise.get_or_create(test_user.id, exercise_d3.id)
        first.ease_factor = 2.0
        db_session.commit()
        second = UserGrammarExercise.get_or_create(test_user.id, exercise_d3.id)
        assert second.ease_factor == 2.0


class TestGetOrCreateConcurrency:
    def test_idempotent_no_duplicate(self, db_session, test_user, exercise_d1):
        """Calling get_or_create twice creates only one row."""
        p1 = UserGrammarExercise.get_or_create(test_user.id, exercise_d1.id)
        db_session.commit()
        p2 = UserGrammarExercise.get_or_create(test_user.id, exercise_d1.id)
        assert p1.id == p2.id
        count = (db_session.query(UserGrammarExercise)
                 .filter_by(user_id=test_user.id, exercise_id=exercise_d1.id)
                 .count())
        assert count == 1

    def test_integrity_error_returns_existing(self, db_session, test_user, exercise_d1):
        """Race condition: begin_nested raises IntegrityError → existing row returned, no raise."""
        from sqlalchemy.exc import IntegrityError
        from unittest.mock import patch, MagicMock
        from app.utils.db import db as _db

        pre = UserGrammarExercise(test_user.id, exercise_d1.id)
        db_session.add(pre)
        db_session.commit()

        class _FailedNested:
            def __enter__(self): raise IntegrityError("dup key", None, None)
            def __exit__(self, *a): return False

        # Simulate: first filter_by returns None (race window), second returns pre
        mock_query = MagicMock()
        first_q = MagicMock()
        first_q.first.return_value = None
        second_q = MagicMock()
        second_q.first.return_value = pre
        mock_query.filter_by.side_effect = [first_q, second_q]

        with patch.object(UserGrammarExercise, 'query', mock_query):
            with patch.object(_db.session, 'begin_nested', return_value=_FailedNested()):
                result = UserGrammarExercise.get_or_create(test_user.id, exercise_d1.id)

        assert result is pre

    def test_topic_status_get_or_create_idempotent(self, db_session, test_user, topic):
        """UserGrammarTopicStatus.get_or_create called twice creates only one row."""
        s1 = UserGrammarTopicStatus.get_or_create(test_user.id, topic.id)
        db_session.commit()
        s2 = UserGrammarTopicStatus.get_or_create(test_user.id, topic.id)
        assert s1.id == s2.id
        count = (db_session.query(UserGrammarTopicStatus)
                 .filter_by(user_id=test_user.id, topic_id=topic.id)
                 .count())
        assert count == 1
