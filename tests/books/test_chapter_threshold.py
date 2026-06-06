"""Chapter "read" threshold is unified (finding #17).

A chapter scrolled to CHAPTER_COMPLETION_THRESHOLD (0.99) is treated as read
everywhere — progress %, total_chapters_read and chapter XP — not only by the
daily reading slot. Previously stats/XP demanded exactly 1.0, so a 0.99 chapter
was "read but not credited".
"""
from __future__ import annotations

from app.books.progress import _progress_from_records
from app.books.reading_session import CHAPTER_COMPLETION_THRESHOLD


class _Rec:
    def __init__(self, pct: float):
        self.offset_pct = pct


def test_threshold_is_below_one():
    assert CHAPTER_COMPLETION_THRESHOLD == 0.99


def test_chapter_at_threshold_counts_as_complete():
    # Single chapter at 0.99 of 1 → fully complete (100%), not 99% partial.
    assert _progress_from_records([_Rec(CHAPTER_COMPLETION_THRESHOLD)], 1) == 100.0


def test_chapter_below_threshold_is_partial():
    pct = CHAPTER_COMPLETION_THRESHOLD - 0.01
    result = _progress_from_records([_Rec(pct)], 1)
    assert result < 100.0
    assert abs(result - pct * 100.0) < 0.001
