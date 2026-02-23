"""Tests for app.srs.utils — count_srs_states and count_srs_states_with_accuracy."""
from datetime import datetime, timedelta, timezone

import pytest

from app.srs.mixins import SRSFieldsMixin
from app.srs.utils import count_srs_states, count_srs_states_with_accuracy


class FakeSRSItem(SRSFieldsMixin):
    """Lightweight SRS item for testing (inherits classify/is_due from mixin)."""

    def __init__(self, state='new', interval=0, next_review=None,
                 correct_count=0, incorrect_count=0):
        self.state = state
        self.interval = interval
        self.next_review = next_review
        self.correct_count = correct_count
        self.incorrect_count = incorrect_count


# ---------------------------------------------------------------------------
# count_srs_states
# ---------------------------------------------------------------------------

class TestCountSrsStates:
    """Tests for count_srs_states()."""

    def test_empty_list(self):
        result = count_srs_states([])
        assert result == {
            'new_count': 0,
            'learning_count': 0,
            'review_count': 0,
            'mastered_count': 0,
            'total': 0,
            'due_today': 0,
        }

    def test_all_new(self):
        items = [FakeSRSItem(state='new') for _ in range(3)]
        result = count_srs_states(items)
        assert result['new_count'] == 3
        assert result['total'] == 3
        assert result['due_today'] == 3

    def test_mixed_states(self):
        """new + learning (due) + review (not due) + mastered (not due) + relearning (due)."""
        far_future = datetime.now(timezone.utc) + timedelta(days=30)
        items = [
            FakeSRSItem(state='new'),
            FakeSRSItem(state='learning', next_review=datetime.now(timezone.utc) - timedelta(hours=1)),
            FakeSRSItem(state='review', interval=10, next_review=far_future),
            FakeSRSItem(state='review', interval=200, next_review=far_future),  # mastered
            FakeSRSItem(state='relearning', next_review=datetime.now(timezone.utc) - timedelta(hours=1)),
        ]
        result = count_srs_states(items)
        assert result['new_count'] == 1
        assert result['learning_count'] == 2   # learning + relearning
        assert result['review_count'] == 1
        assert result['mastered_count'] == 1
        assert result['total'] == 5
        # due: new(1) + learning due(1) + relearning due(1) = 3
        assert result['due_today'] == 3

    def test_none_state_counted_as_new(self):
        """Records with state=None should classify as 'new'."""
        items = [FakeSRSItem(state=None)]
        result = count_srs_states(items)
        assert result['new_count'] == 1
        assert result['due_today'] == 1

    def test_review_due_today(self):
        """Review item whose next_review is in the past counts as due."""
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        items = [FakeSRSItem(state='review', interval=10, next_review=past)]
        result = count_srs_states(items)
        assert result['review_count'] == 1
        assert result['due_today'] == 1

    def test_mastered_due_today(self):
        """Mastered item (interval >= 180) whose next_review is in the past."""
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        items = [FakeSRSItem(state='review', interval=200, next_review=past)]
        result = count_srs_states(items)
        assert result['mastered_count'] == 1
        assert result['due_today'] == 1

    def test_learning_not_due(self):
        """Learning item with future next_review is not due."""
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        items = [FakeSRSItem(state='learning', next_review=future)]
        result = count_srs_states(items)
        assert result['learning_count'] == 1
        assert result['due_today'] == 0

    def test_accepts_generator(self):
        """Should work with any iterable, not just lists."""
        def gen():
            yield FakeSRSItem(state='new')
            yield FakeSRSItem(state='new')

        result = count_srs_states(gen())
        assert result['new_count'] == 2
        assert result['total'] == 2


# ---------------------------------------------------------------------------
# count_srs_states_with_accuracy
# ---------------------------------------------------------------------------

class TestCountSrsStatesWithAccuracy:
    """Tests for count_srs_states_with_accuracy()."""

    def test_accuracy_calculation(self):
        """18 correct / 2 incorrect = 90.0%."""
        items = [
            FakeSRSItem(state='review', interval=10,
                        next_review=datetime.now(timezone.utc) - timedelta(hours=1),
                        correct_count=10, incorrect_count=1),
            FakeSRSItem(state='review', interval=15,
                        next_review=datetime.now(timezone.utc) - timedelta(hours=1),
                        correct_count=8, incorrect_count=1),
        ]
        result = count_srs_states_with_accuracy(items)
        assert result['accuracy'] == 90.0
        assert result['review_count'] == 2
        assert result['total'] == 2

    def test_zero_attempts(self):
        """No attempts at all => accuracy 0."""
        items = [FakeSRSItem(state='new', correct_count=0, incorrect_count=0)]
        result = count_srs_states_with_accuracy(items)
        assert result['accuracy'] == 0
        assert result['new_count'] == 1

    def test_none_counts_treated_as_zero(self):
        """correct_count=None / incorrect_count=None should not crash."""
        items = [FakeSRSItem(state='new')]
        items[0].correct_count = None
        items[0].incorrect_count = None
        result = count_srs_states_with_accuracy(items)
        assert result['accuracy'] == 0

    def test_perfect_accuracy(self):
        """All correct, no incorrect => 100%."""
        items = [FakeSRSItem(state='review', interval=10,
                             next_review=datetime.now(timezone.utc) - timedelta(hours=1),
                             correct_count=20, incorrect_count=0)]
        result = count_srs_states_with_accuracy(items)
        assert result['accuracy'] == 100.0

    def test_includes_all_count_keys(self):
        """Result should contain all count_srs_states keys plus accuracy."""
        result = count_srs_states_with_accuracy([])
        expected_keys = {
            'new_count', 'learning_count', 'review_count',
            'mastered_count', 'total', 'due_today', 'accuracy',
        }
        assert set(result.keys()) == expected_keys
