"""Reading progress math for books.

Single source of truth for converting per-chapter ``offset_pct`` rows into
a whole-book progress percentage. Replaces the legacy ``sum(offset_pct) /
total_chapters`` formula, which underreports progress whenever a user has
finished some chapters and is partway through another (a finished chapter
counted only as ``offset_pct=1.0``, ignoring its weight relative to the
remaining incomplete tail).
"""
from __future__ import annotations

from typing import Iterable

from app.books.models import Chapter, UserChapterProgress


def _progress_from_records(records: Iterable, total_chapters: int) -> float:
    if total_chapters <= 0:
        return 0.0
    completed = 0
    max_partial = 0.0
    for record in records:
        pct = float(record.offset_pct or 0.0)
        if pct >= 1.0:
            completed += 1
        elif pct > max_partial:
            max_partial = pct
    progress = (completed + max_partial) / total_chapters
    return max(0.0, min(progress * 100.0, 100.0))


def compute_book_progress_percent(user_id: int, book_id: int, session) -> float:
    """Return overall reading progress for a book as a 0..100 float.

    progress = (completed_chapters + max_partial_of_incomplete) / total_chapters

    ``session`` accepts either a SQLAlchemy session or the Flask-SQLAlchemy
    ``db`` extension (which exposes ``.session``).
    """
    sess = getattr(session, 'session', session)
    total_chapters = sess.query(Chapter).filter(Chapter.book_id == book_id).count()
    if total_chapters == 0:
        return 0.0
    records = (
        sess.query(UserChapterProgress)
        .join(Chapter, UserChapterProgress.chapter_id == Chapter.id)
        .filter(
            Chapter.book_id == book_id,
            UserChapterProgress.user_id == user_id,
        )
        .all()
    )
    return _progress_from_records(records, total_chapters)
