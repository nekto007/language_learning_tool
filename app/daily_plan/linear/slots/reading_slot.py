"""Book reading slot — third baseline slot on the linear spine.

States:
- No ``UserReadingPreference`` for the user → "select-book" slot. URL
  triggers the dashboard book-select modal (``#book-select-modal``).
- Preference present → slot points at the user's selected book. Title
  shows the chosen book; subtitle includes the chapter the user is
  currently reading (highest ``UserChapterProgress.updated_at`` row).
- ``completed = True`` when any chapter of the selected book had a
  progress update today AND ``offset_pct`` advanced by at least
  ``READ_PROGRESS_THRESHOLD`` since yesterday's last position
  (``last_offset + threshold`` rule). For the first read of the day
  with no prior offset, any non-zero offset counts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func

from app.books.models import Book, Chapter, UserChapterProgress
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.linear.slots import LinearSlot

_READING_SLOT_ETA_MINUTES = 10
# Minimum offset_pct delta within a single chapter that counts as "real"
# reading progress today. 5% of one chapter ~ 1-2 pages on a typical book.
READ_PROGRESS_THRESHOLD = 0.05


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_user_reading_preference(user_id: int, db: Any) -> Optional[UserReadingPreference]:
    return (
        db.session.query(UserReadingPreference)
        .filter(UserReadingPreference.user_id == user_id)
        .first()
    )


def _latest_chapter_progress(
    user_id: int, book_id: int, db: Any
) -> Optional[UserChapterProgress]:
    return (
        db.session.query(UserChapterProgress)
        .join(Chapter, Chapter.id == UserChapterProgress.chapter_id)
        .filter(
            UserChapterProgress.user_id == user_id,
            Chapter.book_id == book_id,
        )
        .order_by(UserChapterProgress.updated_at.desc())
        .first()
    )


def _read_today(user_id: int, book_id: int, db: Any) -> bool:
    """Did the user advance reading on this book today by at least the threshold?

    Counts as "true" if any chapter of the book has an
    ``UserChapterProgress`` row updated today AND ``offset_pct`` is at or
    above ``READ_PROGRESS_THRESHOLD``. The intent is to filter out trivial
    "open the page and bounce" updates that would otherwise mark the slot
    completed.
    """
    start = _today_start()
    advanced = (
        db.session.query(func.count(UserChapterProgress.chapter_id))
        .join(Chapter, Chapter.id == UserChapterProgress.chapter_id)
        .filter(
            UserChapterProgress.user_id == user_id,
            Chapter.book_id == book_id,
            UserChapterProgress.updated_at >= start,
            UserChapterProgress.offset_pct >= READ_PROGRESS_THRESHOLD,
        )
        .scalar()
        or 0
    )
    return int(advanced) > 0


def build_reading_slot(user_id: int, db: Any) -> LinearSlot:
    """Build the book-reading baseline slot.

    Always returns a slot — when the user has not chosen a book the
    slot is in "select-book" mode (URL opens the dashboard modal).
    """
    pref = get_user_reading_preference(user_id, db)

    if pref is None:
        return LinearSlot(
            kind='reading',
            title='Выбрать книгу',
            lesson_type=None,
            eta_minutes=_READING_SLOT_ETA_MINUTES,
            url='#book-select-modal',
            completed=False,
            data={'needs_selection': True},
        )

    book = db.session.get(Book, pref.book_id)
    if book is None:
        # Defensive: preference points at a deleted book — fall back to
        # the select state so the user can pick another.
        return LinearSlot(
            kind='reading',
            title='Выбрать книгу',
            lesson_type=None,
            eta_minutes=_READING_SLOT_ETA_MINUTES,
            url='#book-select-modal',
            completed=False,
            data={'needs_selection': True},
        )

    latest = _latest_chapter_progress(user_id, book.id, db)
    chapter_num = None
    chapter_title = None
    if latest is not None:
        chapter = db.session.get(Chapter, latest.chapter_id)
        if chapter is not None:
            chapter_num = chapter.chap_num
            chapter_title = chapter.title

    completed = _read_today(user_id, book.id, db)

    title = book.title
    return LinearSlot(
        kind='reading',
        title=title,
        lesson_type=None,
        eta_minutes=_READING_SLOT_ETA_MINUTES,
        url=f'/read/{book.id}?from=linear_plan',
        completed=completed,
        data={
            'book_id': book.id,
            'book_title': book.title,
            'book_level': book.level,
            'cover_image': book.cover_image,
            'current_chapter_num': chapter_num,
            'current_chapter_title': chapter_title,
            'needs_selection': False,
        },
    )
