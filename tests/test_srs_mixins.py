# tests/test_srs_mixins.py
"""Tests for SRSFieldsMixin classification methods."""
from datetime import datetime, timedelta, timezone

import pytest

from app.srs.constants import MASTERED_THRESHOLD_DAYS
from app.srs.mixins import SRSFieldsMixin


class FakeSRSItem(SRSFieldsMixin):
    """Fake SRS item for testing the mixin without a real DB model."""

    def __init__(
        self,
        state: str | None = 'new',
        interval: int | None = None,
        next_review: datetime | None = None,
        correct_count: int | None = None,
        incorrect_count: int | None = None,
    ):
        self.state = state
        self.interval = interval
        self.next_review = next_review
        self.correct_count = correct_count
        self.incorrect_count = incorrect_count


# ── classify() ────────────────────────────────────────────────────────

class TestClassify:
    def test_state_new(self):
        item = FakeSRSItem(state='new')
        assert item.classify() == 'new'

    def test_state_none_defaults_to_new(self):
        item = FakeSRSItem(state=None)
        assert item.classify() == 'new'

    def test_state_learning(self):
        item = FakeSRSItem(state='learning')
        assert item.classify() == 'learning'

    def test_state_relearning(self):
        item = FakeSRSItem(state='relearning')
        assert item.classify() == 'learning'

    def test_state_review_not_mastered(self):
        item = FakeSRSItem(state='review', interval=30)
        assert item.classify() == 'review'

    def test_state_review_mastered_at_threshold(self):
        item = FakeSRSItem(state='review', interval=MASTERED_THRESHOLD_DAYS)
        assert item.classify() == 'mastered'

    def test_state_review_mastered_above_threshold(self):
        item = FakeSRSItem(state='review', interval=MASTERED_THRESHOLD_DAYS + 50)
        assert item.classify() == 'mastered'

    def test_state_review_zero_interval(self):
        item = FakeSRSItem(state='review', interval=0)
        assert item.classify() == 'review'

    def test_state_review_none_interval(self):
        item = FakeSRSItem(state='review', interval=None)
        assert item.classify() == 'review'

    def test_unknown_state_falls_back_to_new(self):
        item = FakeSRSItem(state='unknown_state')
        assert item.classify() == 'new'


# ── is_due ────────────────────────────────────────────────────────────

class TestIsDue:
    def test_new_always_due(self):
        item = FakeSRSItem(state='new')
        assert item.is_due is True

    def test_past_next_review_is_due(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        item = FakeSRSItem(state='review', next_review=past)
        assert item.is_due is True

    def test_future_next_review_not_due(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        item = FakeSRSItem(state='review', next_review=future)
        assert item.is_due is False

    def test_none_next_review_is_due(self):
        item = FakeSRSItem(state='review', next_review=None)
        assert item.is_due is True

    def test_naive_datetime_treated_as_utc(self):
        """A naive datetime in the past should still be recognised as due."""
        past_naive = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
        item = FakeSRSItem(state='review', next_review=past_naive)
        assert item.is_due is True

    def test_state_none_is_due(self):
        item = FakeSRSItem(state=None)
        assert item.is_due is True


# ── is_mastered ───────────────────────────────────────────────────────

class TestIsMastered:
    def test_review_at_threshold(self):
        item = FakeSRSItem(state='review', interval=MASTERED_THRESHOLD_DAYS)
        assert item.is_mastered is True

    def test_review_below_threshold(self):
        item = FakeSRSItem(state='review', interval=30)
        assert item.is_mastered is False

    def test_learning_above_threshold(self):
        """Only 'review' state qualifies for mastered."""
        item = FakeSRSItem(state='learning', interval=200)
        assert item.is_mastered is False

    def test_review_none_interval(self):
        item = FakeSRSItem(state='review', interval=None)
        assert item.is_mastered is False

    def test_new_state_not_mastered(self):
        item = FakeSRSItem(state='new', interval=MASTERED_THRESHOLD_DAYS)
        assert item.is_mastered is False


# ── accuracy ──────────────────────────────────────────────────────────

class TestAccuracy:
    def test_eighty_percent(self):
        item = FakeSRSItem(correct_count=8, incorrect_count=2)
        assert item.accuracy == 80.0

    def test_zero_attempts(self):
        item = FakeSRSItem(correct_count=0, incorrect_count=0)
        assert item.accuracy == 0.0

    def test_none_counts_treated_as_zero(self):
        item = FakeSRSItem(correct_count=None, incorrect_count=None)
        assert item.accuracy == 0.0

    def test_hundred_percent(self):
        item = FakeSRSItem(correct_count=10, incorrect_count=0)
        assert item.accuracy == 100.0

    def test_rounding(self):
        item = FakeSRSItem(correct_count=1, incorrect_count=2)
        assert item.accuracy == 33.3
