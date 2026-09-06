"""Reading item builder for the unified daily plan.

Returns a ``PlanItem`` for the user's chosen book when a valid preference
exists. Returns None when no preference is set, when the referenced book is
gone (stale row), or when the user may not open it (draft / revoked ``books``
module / expired licence); the orchestrator then adds a ``setup_book`` item to
the setup section instead. The access gate is the same one the reader routes
enforce — a required slot the user cannot open would hold ``day_secured``
hostage until midnight.

Completion is gated on real reading activity: the user must have crossed
the offset_pct threshold AND spent today's reading target on the selected
book. Opening and closing the book without progress never marks the item done.
When the selected book is fully read, this builder returns None so the plan
can ask the user to choose the next book instead of assigning a dead slot.
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


def book_access_ok_for_reading(user_id: int, book: Any, db: Any) -> bool:
    """Return False when the plan's owner cannot actually open ``book``.

    Mirrors the reader routes (``app/books/routes.py::read_book``): a draft is
    invisible to non-admins (404) and ``can_user_access_book`` answers the
    rights / module question (403). Without this check a required reading slot
    can point at a book the user is not allowed to open — the slot is then
    uncompletable and ``day_secured`` is out of reach for the whole day.
    """
    from app.auth.models import User
    from app.books.access import can_user_access_book

    if book is None:
        return False

    user = db.session.get(User, user_id)
    if user is None:
        logger.warning("reading_item user=%s missing_user access_denied", user_id)
        return False

    # info, not warning: a draft or a title the user has no rights to is an
    # ordinary, permanent state, and this gate runs on every plan assembly
    # (required slot, optional slot, snapshot overlay, perfect-day sweeper).
    # At warning level one such user emits several lines per dashboard render
    # forever and buries the anomalies below.
    if not book.is_published and not getattr(user, 'is_admin', False):
        logger.info("reading_item user=%s book=%s draft_not_readable", user_id, book.id)
        return False

    if not can_user_access_book(user, book):
        logger.info("reading_item user=%s book=%s access_denied", user_id, book.id)
        return False

    return True


def _book_is_actionable_for_reading(user_id: int, book_id: int, db: Any) -> bool:
    """Return False when the selected book cannot produce a useful reading slot."""
    book = db.session.get(Book, book_id)
    if book is None:
        logger.warning("reading_item user=%s book=%s not_found preference_stale", user_id, book_id)
        return False

    if not book_access_ok_for_reading(user_id, book, db):
        return False

    has_chapter = (
        db.session.query(Chapter.id)
        .filter(Chapter.book_id == book.id)
        .first()
    )
    if has_chapter is None:
        logger.warning("reading_item user=%s book=%s has_no_chapters", user_id, book.id)
        return False

    from app.books.progress import get_book_completion_state

    completion_state = get_book_completion_state(user_id, book.id, db)
    if completion_state['is_completed']:
        logger.info("reading_item user=%s book=%s already_completed", user_id, book.id)
        return False
    return True


# Item 16 (2026-09-06): picking a book is the reading goal. The first pick
# turns the goal on at this norm; later picks leave the setting alone so a
# learner who chose «по желанию» is not re-enrolled by switching books.
DEFAULT_READING_GOAL_MINUTES = 5


def ensure_reading_goal_on_first_book(user_id: int, db: Any) -> bool:
    """Set the daily reading goal to the default when it is still unset (0).

    Flush-only; the caller commits. Returns True when the goal was set.
    ``StudySettings.get_settings`` is deliberately not used: it commits when
    it creates the row, which would persist the caller's pending preference
    before the goal is set and break the caller's rollback (Codex review).
    """
    from app.study.models import StudySettings

    settings = (
        db.session.query(StudySettings)
        .filter_by(user_id=user_id)
        .with_for_update()
        .first()
    )
    if settings is None:
        settings = StudySettings(user_id=user_id, reading_minutes_per_day=DEFAULT_READING_GOAL_MINUTES)
        db.session.add(settings)
        db.session.flush()
        return True
    if int(settings.reading_minutes_per_day or 0) > 0:
        return False
    settings.reading_minutes_per_day = DEFAULT_READING_GOAL_MINUTES
    db.session.flush()
    return True


def reading_goal_enabled(user_id: int, db: Any) -> bool:
    """True when the learner set a daily reading goal (minutes > 0).

    Item 14: reading is optional by default. Only a learner who chose a goal
    gets a *required* reading slot; everyone else sees the book in
    «Дополнительно» and the day closes without it.
    """
    from app.study.models import StudySettings

    minutes = (
        StudySettings.query.with_entities(StudySettings.reading_minutes_per_day)
        .filter_by(user_id=user_id)
        .scalar()
    )
    return bool(minutes and int(minutes) > 0)


def reading_preference_needs_setup(user_id: int, db: Any) -> bool:
    """Return True when the plan should show the setup-book card."""
    pref = get_user_reading_preference(user_id, db)
    if pref is None or pref.book_id is None:
        return True
    return not _book_is_actionable_for_reading(user_id, int(pref.book_id), db)


def _read_today(user_id: int, book_id: Optional[int], db: Any) -> bool:
    """Return True when today's reading slot is done for ``book_id``.

    Two signals are accepted, either of which closes the slot:
      1. ``StreakEvent(source='linear_book_reading')`` for today, **scoped to
         this ``book_id``** via ``details.book_id`` — written by
         ``maybe_award_book_reading_xp`` after a qualifying session. The
         book scope means switching the preference book mid-day doesn't carry
         a different book's completion over to the new one.
      2. ``is_daily_reading_target_met_today`` for this book — independent
         fallback so the dashboard tile flips green as soon as the time gate
         is met, even if the XP-award path never landed (e.g. sendBeacon close
         dropped on tab navigation). Also covers legacy events that predate
         the ``book_id`` detail.
    """
    if book_id is None:
        return False

    from app.achievements.models import StreakEvent
    from app.books.reading_session import is_daily_reading_target_met_today
    from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date

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

    if not _book_is_actionable_for_reading(user_id, book.id, db):
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

    from app.books.reading_session import (
        get_book_reading_seconds_today,
        get_daily_reading_target_seconds,
    )
    from app.utils.time_utils import get_user_local_date

    today_target_seconds = get_daily_reading_target_seconds(
        get_user_local_date(user_id, db), user_id=user_id,
    )
    time_spent_seconds = get_book_reading_seconds_today(user_id, book.id, db)
    gate_reached = time_spent_seconds >= today_target_seconds

    priority = focus == 'reading'

    target_minutes = today_target_seconds // 60
    subtitle_parts: list[str] = []
    if chapter_num is not None:
        subtitle_parts.append(f'Глава {chapter_num}')
    if chapter_title:
        subtitle_parts.append(chapter_title)
    subtitle_parts.append(f'Норма дня — {target_minutes} мин')

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
        eta_minutes=target_minutes,
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
            'gate_seconds': today_target_seconds,
            'gate_reached': gate_reached,
        },
    )
