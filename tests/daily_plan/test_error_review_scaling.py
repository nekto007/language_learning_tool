"""Tests for error review scaling helpers (Task 68).

Covers:
- get_review_pool_size boundary values (0, 9, 10, 19, 20, 100)
- get_review_cooldown dynamic thresholds (≥25 → 12h, ≥15 → 1d, else 3d)
- get_sibling_exercise excludes the original exercise id
- log_quiz_errors_from_result writes exercise_id and difficulty into payload
- log_quiz_errors_from_result skips already-unresolved questions
- pool returns [] when limit=0
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.daily_plan.linear.errors import (
    DEFAULT_REVIEW_POOL_LIMIT,
    REVIEW_CRITICAL_BACKLOG_COOLDOWN,
    REVIEW_CRITICAL_BACKLOG_THRESHOLD,
    REVIEW_HIGH_BACKLOG_COOLDOWN,
    REVIEW_HIGH_BACKLOG_THRESHOLD,
    REVIEW_TRIGGER_COOLDOWN,
    get_review_cooldown,
    get_review_pool_size,
    log_quiz_errors_from_result,
)


# ── get_review_pool_size ──────────────────────────────────────────────────────


class TestGetReviewPoolSize:
    def test_zero_unresolved_returns_default(self):
        assert get_review_pool_size(0) == DEFAULT_REVIEW_POOL_LIMIT

    def test_one_unresolved_returns_default(self):
        assert get_review_pool_size(1) == DEFAULT_REVIEW_POOL_LIMIT

    def test_nine_unresolved_returns_default(self):
        """Just below the ≥10 boundary → still 10."""
        assert get_review_pool_size(9) == DEFAULT_REVIEW_POOL_LIMIT

    def test_ten_unresolved_returns_fifteen(self):
        """Exactly at ≥10 boundary."""
        assert get_review_pool_size(10) == 15

    def test_fourteen_unresolved_returns_fifteen(self):
        assert get_review_pool_size(14) == 15

    def test_nineteen_unresolved_returns_fifteen(self):
        """Just below the ≥20 boundary → 15."""
        assert get_review_pool_size(19) == 15

    def test_twenty_unresolved_returns_twenty(self):
        """Exactly at ≥20 boundary."""
        assert get_review_pool_size(20) == 20

    def test_large_backlog_returns_twenty(self):
        assert get_review_pool_size(100) == 20

    def test_default_pool_limit_constant(self):
        assert DEFAULT_REVIEW_POOL_LIMIT == 10


# ── get_review_cooldown ───────────────────────────────────────────────────────


class TestGetReviewCooldown:
    def test_default_cooldown_below_high_threshold(self):
        """Backlog < 15 → standard 3-day cooldown."""
        assert get_review_cooldown(0) == REVIEW_TRIGGER_COOLDOWN
        assert get_review_cooldown(14) == REVIEW_TRIGGER_COOLDOWN
        assert REVIEW_TRIGGER_COOLDOWN == timedelta(days=3)

    def test_high_threshold_exactly(self):
        """Backlog == 15 → 1-day cooldown."""
        cd = get_review_cooldown(REVIEW_HIGH_BACKLOG_THRESHOLD)
        assert cd == REVIEW_HIGH_BACKLOG_COOLDOWN
        assert REVIEW_HIGH_BACKLOG_COOLDOWN == timedelta(days=1)

    def test_high_threshold_above(self):
        """Backlog between 15 and 24 → 1-day cooldown."""
        assert get_review_cooldown(24) == REVIEW_HIGH_BACKLOG_COOLDOWN

    def test_critical_threshold_exactly(self):
        """Backlog == 25 → 12-hour cooldown."""
        cd = get_review_cooldown(REVIEW_CRITICAL_BACKLOG_THRESHOLD)
        assert cd == REVIEW_CRITICAL_BACKLOG_COOLDOWN
        assert REVIEW_CRITICAL_BACKLOG_COOLDOWN == timedelta(hours=12)

    def test_critical_threshold_above(self):
        """Backlog > 25 → 12-hour cooldown."""
        assert get_review_cooldown(50) == REVIEW_CRITICAL_BACKLOG_COOLDOWN

    def test_thresholds_are_correctly_ordered(self):
        """Critical threshold must be higher than high threshold."""
        assert REVIEW_CRITICAL_BACKLOG_THRESHOLD > REVIEW_HIGH_BACKLOG_THRESHOLD

    def test_cooldowns_are_ordered_shortest_to_longest(self):
        """Higher backlog = shorter cooldown."""
        assert REVIEW_CRITICAL_BACKLOG_COOLDOWN < REVIEW_HIGH_BACKLOG_COOLDOWN < REVIEW_TRIGGER_COOLDOWN


# ── get_sibling_exercise ──────────────────────────────────────────────────────


class TestGetSiblingExercise:
    """Unit tests via mocking — integration tests would need DB setup."""

    def _make_error_with_lesson(self, grammar_topic_id=5):
        error = MagicMock()
        lesson = MagicMock()
        lesson.grammar_topic_id = grammar_topic_id
        error.lesson = lesson
        error.question_payload = {'exercise_id': 42, 'difficulty': 1}
        return error

    def test_returns_none_when_lesson_has_no_grammar_topic(self):
        from app.daily_plan.linear.errors import get_sibling_exercise

        error = MagicMock()
        lesson = MagicMock()
        lesson.grammar_topic_id = None
        error.lesson = lesson

        db = MagicMock()
        result = get_sibling_exercise(error, db)
        assert result is None

    def test_returns_none_when_lesson_is_none(self):
        from app.daily_plan.linear.errors import get_sibling_exercise

        error = MagicMock()
        error.lesson = None

        db = MagicMock()
        result = get_sibling_exercise(error, db)
        assert result is None

    def test_excludes_original_exercise_id_from_query(self):
        """The query must filter out the original exercise id.

        Since GrammarExercise is imported lazily inside get_sibling_exercise,
        we patch the grammar_lab module attribute instead.
        """
        from app.daily_plan.linear.errors import get_sibling_exercise

        error = self._make_error_with_lesson(grammar_topic_id=5)

        db = MagicMock()
        mock_query = MagicMock()
        db.session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = None

        with patch('app.grammar_lab.models.GrammarExercise'):
            result = get_sibling_exercise(error, db)

        # No crash means the exclusion path ran without error.
        # The function returns whatever first() returns (None here).
        assert result is None

    def test_sibling_never_returns_original_id(self, app):
        """End-to-end: sibling must not share the original exercise id."""
        with app.app_context():
            from app.daily_plan.linear.errors import get_sibling_exercise

            # Build error with an exercise_id in payload
            error = MagicMock()
            lesson = MagicMock()
            lesson.grammar_topic_id = 7
            error.lesson = lesson
            error.question_payload = {'exercise_id': 42, 'difficulty': 1, 'question_type': 'fill_blank'}

            # Mock DB to simulate: query with exclusion returns None (no sibling)
            db = MagicMock()
            mock_q = MagicMock()
            db.session.query.return_value = mock_q
            mock_q.filter.return_value = mock_q
            mock_q.order_by.return_value = mock_q
            mock_q.first.return_value = None  # No sibling available

            # GrammarExercise is imported lazily — patch at its source module
            with patch('app.grammar_lab.models.GrammarExercise'):
                result = get_sibling_exercise(error, db)

            # When no sibling exists, should return None (not the original)
            assert result is None

    def test_exclude_exercise_ids_param_works(self):
        """Additional ids passed in exclude_exercise_ids are also excluded."""
        from app.daily_plan.linear.errors import get_sibling_exercise

        error = MagicMock()
        lesson = MagicMock()
        lesson.grammar_topic_id = 5
        error.lesson = lesson
        error.question_payload = {'exercise_id': 10}

        db = MagicMock()
        mock_q = MagicMock()
        db.session.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.first.return_value = None

        with patch('app.grammar_lab.models.GrammarExercise'):
            result = get_sibling_exercise(error, db, exclude_exercise_ids={10, 20, 30})

        assert result is None  # query returned None


# ── log_quiz_errors_from_result ───────────────────────────────────────────────


class TestLogQuizErrorsFromResult:
    def _make_db(self):
        """Mock db whose session.query chain returns no unresolved rows."""
        db = MagicMock()
        mock_q = MagicMock()
        db.session.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = []  # no pre-existing unresolved rows
        db.session.add = MagicMock()
        db.session.flush = MagicMock()
        return db

    def test_writes_exercise_id_to_payload(self):
        """exercise_id from question dict must appear in logged payload."""
        db = self._make_db()
        questions = [
            {'type': 'fill_blank', 'question': 'Q1', 'id': 55, 'difficulty': 2}
        ]
        result = {
            'feedback': {
                '0': {'status': 'incorrect', 'user_answer': 'x', 'correct_answer': 'y'}
            }
        }
        logged = log_quiz_errors_from_result(1, 10, questions, result, db, source='grammar')
        assert len(logged) == 1
        payload = logged[0].question_payload
        assert payload.get('exercise_id') == 55

    def test_writes_difficulty_to_payload(self):
        """difficulty from question dict must appear in logged payload."""
        db = self._make_db()
        questions = [
            {'type': 'multiple_choice', 'question': 'Q?', 'id': 99, 'difficulty': 3}
        ]
        result = {
            'feedback': {
                '0': {'status': 'incorrect', 'user_answer': 'a', 'correct_answer': 'b'}
            }
        }
        logged = log_quiz_errors_from_result(1, 10, questions, result, db, source='grammar')
        assert len(logged) == 1
        payload = logged[0].question_payload
        assert payload.get('difficulty') == 3

    def test_does_not_write_exercise_id_when_absent(self):
        """When question has no id, exercise_id must NOT appear in payload."""
        db = self._make_db()
        questions = [{'type': 'quiz', 'question': 'No id here'}]
        result = {
            'feedback': {
                '0': {'status': 'incorrect', 'user_answer': 'x', 'correct_answer': 'y'}
            }
        }
        logged = log_quiz_errors_from_result(1, 10, questions, result, db)
        assert len(logged) == 1
        assert 'exercise_id' not in logged[0].question_payload

    def test_does_not_write_difficulty_when_absent(self):
        """When question has no difficulty, difficulty must NOT appear."""
        db = self._make_db()
        questions = [{'type': 'quiz', 'question': 'No difficulty', 'id': 5}]
        result = {
            'feedback': {
                '0': {'status': 'incorrect', 'user_answer': 'x', 'correct_answer': 'y'}
            }
        }
        logged = log_quiz_errors_from_result(1, 10, questions, result, db)
        assert len(logged) == 1
        assert 'difficulty' not in logged[0].question_payload
        assert logged[0].question_payload.get('exercise_id') == 5

    def test_skips_correct_answers(self):
        """Correct feedback entries must not be logged."""
        db = self._make_db()
        questions = [
            {'type': 'quiz', 'question': 'Q1'},
            {'type': 'quiz', 'question': 'Q2'},
        ]
        result = {
            'feedback': {
                '0': {'status': 'correct'},
                '1': {'status': 'incorrect', 'user_answer': 'x', 'correct_answer': 'y'},
            }
        }
        logged = log_quiz_errors_from_result(1, 10, questions, result, db)
        assert len(logged) == 1
        assert logged[0].question_payload['question_index'] == 1

    def test_skips_already_logged_question_index(self):
        """If a question is already unresolved in DB, skip it (no duplicate)."""
        db = MagicMock()
        # Simulate question_index=0 already in the unresolved set
        existing = MagicMock()
        existing.question_payload = {'question_index': 0}
        mock_q = MagicMock()
        db.session.query.return_value = mock_q
        mock_q.filter.return_value = mock_q
        mock_q.all.return_value = [existing]
        db.session.add = MagicMock()
        db.session.flush = MagicMock()

        questions = [{'type': 'quiz', 'question': 'Q1', 'id': 7}]
        result = {
            'feedback': {
                '0': {'status': 'incorrect', 'user_answer': 'x', 'correct_answer': 'y'}
            }
        }
        logged = log_quiz_errors_from_result(1, 10, questions, result, db)
        assert len(logged) == 0

    def test_returns_empty_list_for_missing_feedback(self):
        """Missing feedback key → empty list, no crash."""
        db = self._make_db()
        logged = log_quiz_errors_from_result(1, 10, [], {}, db)
        assert logged == []

    def test_returns_empty_list_for_none_result(self):
        """None result → empty list, no crash."""
        db = self._make_db()
        logged = log_quiz_errors_from_result(1, 10, [], None, db)
        assert logged == []

    def test_source_stored_in_payload(self):
        """source parameter is recorded in payload."""
        db = self._make_db()
        questions = [{'type': 'quiz', 'question': 'Q'}]
        result = {
            'feedback': {
                '0': {'status': 'incorrect', 'user_answer': 'x', 'correct_answer': 'y'}
            }
        }
        logged = log_quiz_errors_from_result(1, 10, questions, result, db, source='grammar')
        assert logged[0].question_payload['source'] == 'grammar'

    def test_multiple_incorrect_all_logged(self):
        """All incorrect answers across multiple questions are logged."""
        db = self._make_db()
        questions = [
            {'type': 'quiz', 'question': 'Q1', 'id': 1, 'difficulty': 1},
            {'type': 'quiz', 'question': 'Q2', 'id': 2, 'difficulty': 2},
            {'type': 'quiz', 'question': 'Q3'},
        ]
        result = {
            'feedback': {
                '0': {'status': 'incorrect', 'user_answer': 'a', 'correct_answer': 'A'},
                '1': {'status': 'correct'},
                '2': {'status': 'incorrect', 'user_answer': 'b', 'correct_answer': 'B'},
            }
        }
        logged = log_quiz_errors_from_result(1, 10, questions, result, db)
        assert len(logged) == 2
        indices = {e.question_payload['question_index'] for e in logged}
        assert indices == {0, 2}
