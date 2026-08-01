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
    # Shared "chapter read" threshold — keep in lock-step with chapter-completion
    # XP / total_chapters_read so a chapter counted as read elsewhere isn't shown
    # as merely partial here.
    from app.books.reading_session import CHAPTER_COMPLETION_THRESHOLD

    if total_chapters <= 0:
        return 0.0
    completed = 0
    max_partial = 0.0
    for record in records:
        pct = float(record.offset_pct or 0.0)
        if pct >= CHAPTER_COMPLETION_THRESHOLD:
            completed += 1
        elif pct > max_partial:
            max_partial = pct
    # NOTE (audit E-054): only the single largest partial chapter is added on
    # top of completed ones — intentionally conservative. Summing every partial
    # chapter's fraction would over-credit scattered skimming; this under-counts
    # diffuse reading instead, which is the safer direction for a progress %.
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


def get_book_completion_state(user_id: int, book_id: int, session) -> dict:
    """Return chapter counts and completion state for a user's book progress."""
    from sqlalchemy import func

    from app.books.reading_session import CHAPTER_COMPLETION_THRESHOLD

    sess = getattr(session, 'session', session)
    total_chapters = (
        sess.query(func.count(Chapter.id))
        .filter(Chapter.book_id == book_id)
        .scalar() or 0
    )
    completed_chapters = (
        sess.query(func.count(UserChapterProgress.chapter_id))
        .join(Chapter, Chapter.id == UserChapterProgress.chapter_id)
        .filter(
            UserChapterProgress.user_id == user_id,
            Chapter.book_id == book_id,
            UserChapterProgress.offset_pct >= CHAPTER_COMPLETION_THRESHOLD,
        )
        .scalar() or 0
    )
    return {
        'total_chapters': int(total_chapters),
        'completed_chapters': int(completed_chapters),
        'is_completed': total_chapters > 0 and completed_chapters >= total_chapters,
    }


def get_completed_book_ids(user_id: int, book_ids: Iterable[int], session) -> set[int]:
    """Return ids of books where every chapter is completed by the user."""
    from sqlalchemy import func

    from app.books.reading_session import CHAPTER_COMPLETION_THRESHOLD

    ids = {int(book_id) for book_id in book_ids if book_id is not None}
    if not ids:
        return set()

    sess = getattr(session, 'session', session)
    chapter_counts = dict(
        sess.query(Chapter.book_id, func.count(Chapter.id))
        .filter(Chapter.book_id.in_(ids))
        .group_by(Chapter.book_id)
        .all()
    )
    if not chapter_counts:
        return set()

    completed_counts = dict(
        sess.query(Chapter.book_id, func.count(UserChapterProgress.chapter_id))
        .join(UserChapterProgress, UserChapterProgress.chapter_id == Chapter.id)
        .filter(
            UserChapterProgress.user_id == user_id,
            Chapter.book_id.in_(ids),
            UserChapterProgress.offset_pct >= CHAPTER_COMPLETION_THRESHOLD,
        )
        .group_by(Chapter.book_id)
        .all()
    )

    return {
        book_id
        for book_id, total in chapter_counts.items()
        if total > 0 and completed_counts.get(book_id, 0) >= total
    }


# Inlined former XPService.calculate_book_chapter_xp (constant 50 XP).
BOOK_CHAPTER_XP = 50


def apply_chapter_completion_effects(user_id: int, book_id: int, chapter, db):
    """Side effects of a chapter crossing ``CHAPTER_COMPLETION_THRESHOLD``.

    Single source for chapter XP, the book milestone notification and the
    ``total_chapters_read`` / ``total_books_completed`` counters — every
    write-path that can complete a chapter (``/api/save-reading-position``,
    ``PATCH /api/progress``, the unload-hint in ``reading-session/end``)
    must call this instead of duplicating the blocks.

    Call ONLY on the just-transitioned save (caller checks ``was_incomplete``):
    the XP award is idempotent per (book, chapter), but the counters are
    guarded solely by that transition check. Flush only — caller commits.
    Returns the chapter XP award result, or None when already awarded.
    """
    import logging

    from app.achievements.xp_service import award_book_chapter_xp_idempotent
    from app.utils.time_utils import get_user_local_date

    logger = logging.getLogger(__name__)
    sess = getattr(db, 'session', db)

    chapter_xp_award = award_book_chapter_xp_idempotent(
        user_id=user_id,
        book_id=book_id,
        chapter_id=chapter.id,
        xp=BOOK_CHAPTER_XP,
        for_date=get_user_local_date(user_id, db),
        db_session=db,
    )

    # Book milestone (off-band notification, transient) — best-effort.
    try:
        from app.daily_plan.milestones import check_book_milestone
        percent = compute_book_progress_percent(user_id, book_id, db)
        check_book_milestone(user_id, book_id, percent, db)
    except Exception:
        logger.warning(
            "book milestone check failed user=%s book=%s",
            user_id, book_id, exc_info=True,
        )

    # Reading counters on UserStatistics — best-effort, flush only.
    try:
        from app.achievements.services import StatisticsService
        stats = StatisticsService.get_or_create_statistics(user_id)
        stats.total_chapters_read = (stats.total_chapters_read or 0) + 1

        # Detect full book completion: every chapter must be read (offset_pct
        # at/above the shared completion threshold).
        completion_state = get_book_completion_state(user_id, book_id, db)
        if completion_state['is_completed']:
            stats.total_books_completed = (stats.total_books_completed or 0) + 1
        sess.flush()
    except Exception:
        logger.warning(
            "book stats update failed user=%s book=%s",
            user_id, book_id, exc_info=True,
        )

    return chapter_xp_award
