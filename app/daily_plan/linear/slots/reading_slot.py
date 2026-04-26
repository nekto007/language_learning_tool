"""Book reading slot — third baseline slot on the linear spine.

States:
- No ``UserReadingPreference`` for the user → "select-book" slot. URL
  triggers the dashboard book-select modal (``#book-select-modal``).
- Preference present → slot points at the user's selected book. Title
  shows the chosen book; subtitle includes the chapter the user is
  currently reading (highest ``UserChapterProgress.updated_at`` row).
- ``completed = True`` when a ``linear_book_reading`` XP award was
  recorded today (see ``save_reading_position`` / ``maybe_award_book_reading_xp``).
  That award is gated on an offset_pct delta of at least
  ``READ_PROGRESS_THRESHOLD``, so re-opening the book at the same
  position never flips the slot to completed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.books.models import Book, Chapter, UserChapterProgress
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.models import UserReadingPreference
from app.daily_plan.linear.slots import LinearSlot

_READING_SLOT_ETA_MINUTES = 10
# Minimum offset_pct delta within a single chapter that counts as "real"
# reading progress today. 5% of one chapter ~ 1-2 pages on a typical book.
READ_PROGRESS_THRESHOLD = 0.05


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


def _read_today(user_id: int, db: Any) -> bool:
    """Did the user earn the ``linear_book_reading`` XP award today?

    The XP award is written by ``save_reading_position`` only when the
    offset_pct delta since the last saved position crosses
    ``READ_PROGRESS_THRESHOLD``. Using the award row as the "read today"
    signal keeps the slot's ``completed`` flag aligned with the XP path
    and prevents trivial "open-and-close" updates from marking the slot
    completed.
    """
    from app.achievements.models import StreakEvent
    from app.daily_plan.linear.xp import (
        LINEAR_XP_EVENT_TYPE,
        get_linear_event_local_date,
    )

    today = get_linear_event_local_date(user_id, db)
    query = db.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.event_date == today,
        StreakEvent.details['source'].astext == 'linear_book_reading',
    )
    return db.session.query(query.exists()).scalar() or False


def build_reading_slot(
    user_id: int, db: Any, *, focus: Optional[str] = None
) -> LinearSlot:
    """Build the book-reading baseline slot.

    Always returns a slot — when the user has not chosen a book the
    slot is in "select-book" mode (URL opens the dashboard modal).

    When ``focus='reading'`` (the user picked reading as their primary
    onboarding focus), ``slot.data['priority']=True`` is set as a hint
    for the UI to render the slot as recommended.
    """
    priority = focus == 'reading'
    pref = get_user_reading_preference(user_id, db)

    if pref is None:
        return LinearSlot(
            kind='reading',
            title='Выбрать книгу',
            lesson_type=None,
            eta_minutes=_READING_SLOT_ETA_MINUTES,
            url='#book-select-modal',
            completed=False,
            data={'needs_selection': True, 'priority': priority},
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
            data={'needs_selection': True, 'priority': priority},
        )

    latest = _latest_chapter_progress(user_id, book.id, db)
    chapter_num = None
    chapter_title = None
    if latest is not None:
        chapter = db.session.get(Chapter, latest.chapter_id)
        if chapter is not None:
            chapter_num = chapter.chap_num
            chapter_title = chapter.title

    completed = _read_today(user_id, db)

    title = book.title
    return LinearSlot(
        kind='reading',
        title=title,
        lesson_type=None,
        eta_minutes=_READING_SLOT_ETA_MINUTES,
        url=build_slot_url(f'/read/{book.id}', LinearSlotKind.BOOK),
        completed=completed,
        data={
            'book_id': book.id,
            'book_title': book.title,
            'book_level': book.level,
            'cover_image': book.cover_image,
            'current_chapter_num': chapter_num,
            'current_chapter_title': chapter_title,
            'needs_selection': False,
            'priority': priority,
        },
    )
