# app/srs/mixins.py
"""
SRS Fields Mixin - provides SRS classification methods for any model
that has the standard SRS columns (state, interval, next_review, etc.).
"""
from datetime import datetime, timezone

from app.srs.constants import MASTERED_THRESHOLD_DAYS


class SRSFieldsMixin:
    """
    Mixin providing SRS classification methods.

    Expects the consuming model to have these columns:
        state, interval, next_review, correct_count, incorrect_count
    """

    def classify(self) -> str:
        """
        Classify this SRS item into a display category.
        Returns one of: 'new', 'learning', 'review', 'mastered'
        """
        state = self.state or 'new'
        if state == 'new':
            return 'new'
        if state in ('learning', 'relearning'):
            return 'learning'
        if state == 'review':
            if self.interval and self.interval >= MASTERED_THRESHOLD_DAYS:
                return 'mastered'
            return 'review'
        return 'new'

    @property
    def is_due(self) -> bool:
        """Check if this item is due for review."""
        state = self.state or 'new'
        if state == 'new':
            return True
        if not self.next_review:
            return True
        nr = self.next_review
        if nr.tzinfo is None:
            nr = nr.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= nr

    @property
    def is_mastered(self) -> bool:
        """Check if this item has reached mastered threshold."""
        return (
            self.state == 'review'
            and self.interval is not None
            and self.interval >= MASTERED_THRESHOLD_DAYS
        )

    @property
    def accuracy(self) -> float:
        """Calculate accuracy percentage."""
        total = (self.correct_count or 0) + (self.incorrect_count or 0)
        if total == 0:
            return 0.0
        return round((self.correct_count or 0) / total * 100, 1)
