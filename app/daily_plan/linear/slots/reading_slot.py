"""Book reading slot — third baseline slot on the linear spine.

States:
- No ``UserReadingPreference`` for the user → "select-book" slot. URL
  triggers the dashboard book-select modal (``#book-select-modal``).
- Preference present → slot points at the user's selected book. Title
  shows the chosen book; subtitle includes the chapter the user is
  currently reading (highest ``UserChapterProgress.updated_at`` row).
- ``completed = True`` when today's book-scoped reading gate is met for the
  selected book. A ``linear_book_reading`` XP event closes only the book it was
  earned on, and the fallback checks today's real reading target.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.books.models import Book, Chapter, UserChapterProgress

logger = logging.getLogger(__name__)
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


def _read_today(user_id: int, book_id: Optional[int], db: Any) -> bool:
    """Return True when today's reading slot is done for ``book_id``.

    Kept in sync with ``app.daily_plan.items.reading._read_today`` for the
    legacy linear slot surface.
    """
    if book_id is None:
        return False

    from app.achievements.models import StreakEvent
    from app.books.reading_session import is_daily_reading_target_met_today
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
        StreakEvent.details['book_id'].astext == str(book_id),
    )
    if db.session.query(query.exists()).scalar() or False:
        return True
    try:
        return is_daily_reading_target_met_today(user_id, book_id, db)
    except Exception:
        logger.warning(
            "reading_slot: is_daily_reading_target_met_today failed user=%s book=%s",
            user_id, book_id, exc_info=True,
        )
        return False


def _compute_level_mismatch(
    user_id: int, book_level: Optional[str], db: Any
) -> tuple[bool, bool]:
    """Return (too_hard, too_easy) flags by comparing book level to the user's
    effective CEFR level. A 2+ level gap in either direction triggers a hint.
    Returns (False, False) when either side cannot be resolved."""
    if not book_level:
        return False, False
    from app.daily_plan.level_utils import (
        _cefr_code_to_order,
        get_user_current_cefr_level,
    )

    user_code = get_user_current_cefr_level(user_id, db)
    user_order = _cefr_code_to_order(user_code, db)
    book_order = _cefr_code_to_order(book_level, db)
    if user_order < 0 or book_order < 0:
        return False, False
    diff = book_order - user_order
    return diff >= 2, diff <= -2


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
        logger.info("reading_slot user=%s state=no_preference focus=%s", user_id, focus)
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
        logger.warning("reading_slot user=%s book=%s not_found preference_stale", user_id, pref.book_id)
        return LinearSlot(
            kind='reading',
            title='Выбрать книгу',
            lesson_type=None,
            eta_minutes=_READING_SLOT_ETA_MINUTES,
            url='#book-select-modal',
            completed=False,
            data={'needs_selection': True, 'priority': priority},
        )

    from app.daily_plan.items.reading import _book_is_actionable_for_reading
    if not _book_is_actionable_for_reading(user_id, book.id, db):
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

    completed = _read_today(user_id, book.id, db)

    from app.books.reading_session import (
        get_book_reading_seconds_today,
        get_daily_reading_target_seconds,
    )
    from app.utils.time_utils import get_user_local_date

    time_spent_seconds = get_book_reading_seconds_today(user_id, book.id, db)
    today_target_seconds = get_daily_reading_target_seconds(
        get_user_local_date(user_id, db)
    )
    gate_reached = time_spent_seconds >= today_target_seconds

    level_too_hard, level_too_easy = _compute_level_mismatch(user_id, book.level, db)

    logger.info(
        "reading_slot user=%s book=%s chapter=%s state=%s priority=%s time=%ss gate=%s",
        user_id, book.id, chapter_num,
        'done_today' if completed else 'pending',
        priority, time_spent_seconds, gate_reached,
    )
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
            'time_spent_seconds': time_spent_seconds,
            'gate_seconds': today_target_seconds,
            'gate_reached': gate_reached,
            'level_too_hard': level_too_hard,
            'level_too_easy': level_too_easy,
        },
    )
