"""Tests for grammar weakness hint in curriculum item builder (Task 67).

Covers:
- _get_weak_grammar_topic_ids returns empty dict when no attempts exist
- weak_topic_hint=True is enrichment-only: PlanItem id (spine) is unchanged
- min_attempts=3 threshold filters out topics with fewer total attempts
- max_accuracy=0.6 boundary: topics at/above 0.6 accuracy are excluded
- threshold boundary: topics exactly at min_attempts are included
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.daily_plan.items.curriculum import (
    _WEAK_ACCURACY_MAX,
    _WEAK_MIN_ATTEMPTS,
    _get_weak_grammar_topic_ids,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_db_with_rows(rows: list) -> Any:
    """Return a mock db whose session.query chain yields `rows`."""
    db = MagicMock()
    (
        db.session.query.return_value
        .join.return_value
        .join.return_value
        .filter.return_value
        .group_by.return_value
        .having.return_value
        .all.return_value
    ) = rows
    return db


def _make_row(topic_id: int, title: str, correct: int, total: int):
    row = MagicMock()
    row.id = topic_id
    row.title = title
    row.correct = correct
    row.total = total
    return row


# ── _get_weak_grammar_topic_ids ───────────────────────────────────────────────


class TestGetWeakGrammarTopicIds:
    def test_returns_empty_dict_when_no_attempts(self, app):
        """Zero UserGrammarExercise rows → empty dict, no exception."""
        with app.app_context():
            db = _make_db_with_rows([])
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert result == {}

    def test_returns_empty_dict_when_all_rows_have_zero_total(self, app):
        """Rows with total=0 are skipped to avoid division by zero."""
        with app.app_context():
            rows = [_make_row(1, 'Articles', correct=0, total=0)]
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert result == {}

    def test_min_attempts_threshold_filters_new_users(self, app):
        """Topics with total < min_attempts are excluded via HAVING clause.

        The HAVING filter runs in SQL, so rows reaching Python already meet
        the threshold. We verify that if `total` equals min_attempts the topic
        IS included (boundary is inclusive).
        """
        with app.app_context():
            # Exactly at threshold, low accuracy → should appear
            rows = [_make_row(5, 'Present Simple', correct=1, total=_WEAK_MIN_ATTEMPTS)]
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert 5 in result, "Topic at exact min_attempts threshold should be included"

    def test_accuracy_below_max_included(self, app):
        """Topic with accuracy below max_accuracy is returned."""
        with app.app_context():
            # accuracy = 1/5 = 0.2, below 0.6
            rows = [_make_row(7, 'Past Perfect', correct=1, total=5)]
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert 7 in result
            assert result[7]['title'] == 'Past Perfect'
            assert abs(result[7]['accuracy'] - 0.2) < 0.001

    def test_accuracy_at_max_excluded(self, app):
        """Topic with accuracy == max_accuracy (0.6) is excluded (strict <)."""
        with app.app_context():
            # accuracy = 3/5 = 0.6 exactly → excluded
            rows = [_make_row(8, 'Conditionals', correct=3, total=5)]
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert 8 not in result

    def test_accuracy_above_max_excluded(self, app):
        """Topic with accuracy above max_accuracy is excluded."""
        with app.app_context():
            # accuracy = 4/5 = 0.8, above 0.6
            rows = [_make_row(9, 'Articles', correct=4, total=5)]
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert 9 not in result

    def test_multiple_topics_mixed_accuracy(self, app):
        """Only topics below accuracy threshold are returned."""
        with app.app_context():
            rows = [
                _make_row(1, 'Weak Topic', correct=1, total=5),   # 0.2 → included
                _make_row(2, 'Strong Topic', correct=4, total=5),  # 0.8 → excluded
                _make_row(3, 'Border Topic', correct=3, total=5),  # 0.6 → excluded
            ]
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert set(result.keys()) == {1}

    def test_accuracy_rounded_to_3_decimals(self, app):
        """Returned accuracy value is rounded to 3 decimal places."""
        with app.app_context():
            # 1/3 = 0.333...
            rows = [_make_row(10, 'Modal Verbs', correct=1, total=3)]
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert 10 in result
            assert result[10]['accuracy'] == round(1 / 3, 3)

    def test_custom_min_attempts_param(self, app):
        """min_attempts parameter can be overridden."""
        with app.app_context():
            # With min_attempts=10, a topic with total=3 would be filtered by HAVING
            # but our mock bypasses SQL, so we test the Python side doesn't break
            rows = []
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db, min_attempts=10)
            assert result == {}

    def test_custom_max_accuracy_param(self, app):
        """max_accuracy parameter can be overridden."""
        with app.app_context():
            # accuracy=0.5, default threshold=0.6 → normally included
            # With max_accuracy=0.4 → excluded
            rows = [_make_row(11, 'Gerunds', correct=2, total=4)]  # 0.5
            db = _make_db_with_rows(rows)

            result_default = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert 11 in result_default

            db2 = _make_db_with_rows(rows)
            result_strict = _get_weak_grammar_topic_ids(user_id=1, db=db2, max_accuracy=0.4)
            assert 11 not in result_strict


# ── Spine invariance ──────────────────────────────────────────────────────────


class TestSpineInvariance:
    """weak_topic_hint enrichment must not alter the PlanItem id (spine)."""

    def test_weak_hint_does_not_change_item_id(self, app):
        """PlanItem.id stays curriculum:lesson:<id> regardless of weak hint."""
        with app.app_context():
            from app.daily_plan.items.curriculum import build_curriculum_item

            mock_lesson = MagicMock()
            mock_lesson.id = 42
            mock_lesson.title = 'Test Lesson'
            mock_lesson.type = 'grammar'
            mock_lesson.number = 1
            mock_lesson.module_id = 1
            mock_lesson.grammar_topic_id = 5

            mock_module = MagicMock()
            mock_module.number = 1
            mock_module.title = 'Module 1'
            mock_module.level = None

            mock_lesson.module = mock_module

            db = MagicMock()

            weak_topics = {5: {'title': 'Articles', 'accuracy': 0.3}}

            with (
                patch('app.daily_plan.items.curriculum.find_next_lesson_linear',
                      return_value=mock_lesson),
                patch('app.daily_plan.items.curriculum._curriculum_done_today',
                      return_value=False),
                patch('app.daily_plan.items.curriculum._get_weak_grammar_topic_ids',
                      return_value=weak_topics),
                patch('app.daily_plan.items.curriculum._get_recent_quiz_scores',
                      return_value=[]),
            ):
                item = build_curriculum_item(user_id=1, db=db)

            assert item is not None
            # Spine (item id) must always be curriculum:lesson:<lesson_id>
            assert item.id == 'curriculum:lesson:42'
            # Enrichment fields are in data only
            assert item.data.get('weak_topic_hint') is True
            assert item.data.get('weak_topic_name') == 'Articles'
            # lesson_id in data is also correct
            assert item.data.get('lesson_id') == 42

    def test_no_weak_hint_when_no_grammar_topic(self, app):
        """Lesson without grammar_topic_id gets no weak_topic_hint."""
        with app.app_context():
            from app.daily_plan.items.curriculum import build_curriculum_item

            mock_lesson = MagicMock()
            mock_lesson.id = 43
            mock_lesson.title = 'Vocab Lesson'
            mock_lesson.type = 'vocabulary'
            mock_lesson.number = 2
            mock_lesson.module_id = 1
            mock_lesson.grammar_topic_id = None

            mock_module = MagicMock()
            mock_module.number = 1
            mock_module.title = 'Module 1'
            mock_module.level = None

            mock_lesson.module = mock_module

            db = MagicMock()

            with (
                patch('app.daily_plan.items.curriculum.find_next_lesson_linear',
                      return_value=mock_lesson),
                patch('app.daily_plan.items.curriculum._curriculum_done_today',
                      return_value=False),
                patch('app.daily_plan.items.curriculum._get_weak_grammar_topic_ids',
                      return_value={7: {'title': 'Some Topic', 'accuracy': 0.2}}),
                patch('app.daily_plan.items.curriculum._get_recent_quiz_scores',
                      return_value=[]),
            ):
                item = build_curriculum_item(user_id=1, db=db)

            assert item is not None
            assert item.id == 'curriculum:lesson:43'
            assert 'weak_topic_hint' not in item.data

    def test_weak_hint_not_added_when_topic_not_weak(self, app):
        """Topic matched but not in weak_topics dict → no hint added."""
        with app.app_context():
            from app.daily_plan.items.curriculum import build_curriculum_item

            mock_lesson = MagicMock()
            mock_lesson.id = 44
            mock_lesson.title = 'Grammar Lesson'
            mock_lesson.type = 'grammar'
            mock_lesson.number = 3
            mock_lesson.module_id = 1
            mock_lesson.grammar_topic_id = 99  # not in weak_topics

            mock_module = MagicMock()
            mock_module.number = 1
            mock_module.title = 'Module 1'
            mock_module.level = None

            mock_lesson.module = mock_module

            db = MagicMock()

            with (
                patch('app.daily_plan.items.curriculum.find_next_lesson_linear',
                      return_value=mock_lesson),
                patch('app.daily_plan.items.curriculum._curriculum_done_today',
                      return_value=False),
                patch('app.daily_plan.items.curriculum._get_weak_grammar_topic_ids',
                      return_value={5: {'title': 'Articles', 'accuracy': 0.3}}),
                patch('app.daily_plan.items.curriculum._get_recent_quiz_scores',
                      return_value=[]),
            ):
                item = build_curriculum_item(user_id=1, db=db)

            assert item is not None
            assert item.id == 'curriculum:lesson:44'
            assert 'weak_topic_hint' not in item.data


# ── Threshold boundary ────────────────────────────────────────────────────────


class TestThresholdBoundary:
    def test_weak_accuracy_constant_is_point_six(self):
        assert _WEAK_ACCURACY_MAX == 0.6

    def test_min_attempts_constant_is_three(self):
        assert _WEAK_MIN_ATTEMPTS == 3

    def test_zero_correct_still_qualifies_as_weak(self, app):
        """A topic with 0 correct answers and enough attempts is weak."""
        with app.app_context():
            rows = [_make_row(20, 'Zero Correct', correct=0, total=3)]
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert 20 in result
            assert result[20]['accuracy'] == 0.0

    def test_high_volume_low_accuracy(self, app):
        """High attempt count with low accuracy is correctly identified as weak."""
        with app.app_context():
            # 10/100 = 0.1 accuracy
            rows = [_make_row(21, 'Hard Topic', correct=10, total=100)]
            db = _make_db_with_rows(rows)
            result = _get_weak_grammar_topic_ids(user_id=1, db=db)
            assert 21 in result
            assert result[21]['accuracy'] == 0.1
