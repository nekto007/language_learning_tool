"""Reading item builder for the unified daily plan.

Returns a ``PlanItem`` for the user's chosen book when a valid preference
exists. Returns None when no preference is set OR the referenced book is
gone (stale row); the orchestrator then adds a ``setup_book`` item to the
setup section instead.

Completion is gated on real reading activity: the user must have crossed
the offset_pct threshold AND spent ``MIN_READING_SECONDS`` reading today.
Opening and closing the book without progress never marks the item done.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.books.models import Book, Chapter, UserChapterProgress
from app.daily_plan.items import PlanItem
from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.models import UserReadingPreference

logger = logging.getLogger(__name__)

_READING_ITEM_ETA_MINUTES = 10


def get_user_reading_preference(user_id: int, db: Any) -> Optional[UserReadingPreference]:
    return (
        db.session.query(UserReadingPreference)
        .filter(UserReadingPreference.user_id == user_id)
        .first()
    )


def _latest_chapter_progress(user_id: int, book_id: int, db: Any) -> Optional[UserChapterProgress]:
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

    Two signals are accepted, either of which closes the slot:
      1. ``StreakEvent(source='linear_book_reading')`` for today — written
         by ``maybe_award_book_reading_xp`` after a qualifying session.
      2. ``is_daily_reading_target_met_today`` for the user's selected book
         — independent fallback so the dashboard tile flips green as soon
         as the time gate is met, even if the XP-award path never landed
         (e.g. sendBeacon close was dropped on tab navigation).
    """
    from app.achievements.models import StreakEvent
    from app.books.reading_session import is_daily_reading_target_met_today
    from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date

    today = get_linear_event_local_date(user_id, db)
    query = db.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.event_date == today,
        StreakEvent.details['source'].astext == 'linear_book_reading',
    )
    if db.session.query(query.exists()).scalar() or False:
        return True
    if book_id is None:
        return False
    try:
        return is_daily_reading_target_met_today(user_id, book_id, db)
    except Exception:
        logger.warning(
            "_read_today: is_daily_reading_target_met_today failed user=%s book=%s",
            user_id, book_id, exc_info=True,
        )
        return False


def build_reading_item(
    user_id: int,
    db: Any,
    *,
    section: str = 'required',
    focus: Optional[str] = None,
) -> Optional[PlanItem]:
    """Return reading PlanItem for the selected book, or None.

    None means: no preference OR preference points at a deleted book.
    Orchestrator should add ``setup_book`` instead.
    """
    pref = get_user_reading_preference(user_id, db)
    if pref is None:
        return None

    book = db.session.get(Book, pref.book_id)
    if book is None:
        logger.warning("reading_item user=%s book=%s not_found preference_stale", user_id, pref.book_id)
        return None

    latest = _latest_chapter_progress(user_id, book.id, db)
    chapter_num = None
    chapter_title = None
    if latest is not None:
        chapter = db.session.get(Chapter, latest.chapter_id)
        if chapter is not None:
            chapter_num = chapter.chap_num
            chapter_title = chapter.title

    completed = _read_today(user_id, book.id, db)

    from app.books.reading_session import MIN_READING_SECONDS, get_book_reading_seconds_today

    time_spent_seconds = get_book_reading_seconds_today(user_id, book.id, db)
    gate_reached = time_spent_seconds >= MIN_READING_SECONDS

    priority = focus == 'reading'

    subtitle_parts: list[str] = []
    if chapter_num is not None:
        subtitle_parts.append(f'Глава {chapter_num}')
    if chapter_title:
        subtitle_parts.append(chapter_title)

    return PlanItem(
        id=f'reading:book:{book.id}',
        section=section,  # type: ignore[arg-type]
        kind='reading',
        title=book.title,
        # NOTE: lesson_type stays None — reading is not a curriculum lesson —
        # the template uses kind='reading' to display the «Чтение книги»
        # label above the book name.
        subtitle=' · '.join(subtitle_parts) if subtitle_parts else None,
        lesson_type=None,
        eta_minutes=_READING_ITEM_ETA_MINUTES,
        url=build_slot_url(f'/read/{book.id}', LinearSlotKind.BOOK),
        completed=completed,
        completion_signal='reading_gate',
        data={
            'book_id': book.id,
            'book_title': book.title,
            'book_level': book.level,
            'cover_image': book.cover_image,
            'current_chapter_num': chapter_num,
            'current_chapter_title': chapter_title,
            'priority': priority,
            'time_spent_seconds': time_spent_seconds,
            'gate_seconds': MIN_READING_SECONDS,
            'gate_reached': gate_reached,
        },
    )
