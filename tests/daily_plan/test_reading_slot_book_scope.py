"""Reading-slot completion is book-scoped (finding #15).

A ``linear_book_reading`` XP event closes the slot only for the book it was
earned on. Switching the preference book mid-day must NOT carry the old book's
done-state over to the new one.
"""
from __future__ import annotations

from app.achievements.models import StreakEvent
from app.daily_plan.items.reading import _read_today
from app.daily_plan.linear.xp import LINEAR_XP_EVENT_TYPE, get_linear_event_local_date
from app.utils.db import db as app_db


def _add_reading_event(db_session, user_id, book_id):
    today = get_linear_event_local_date(user_id, app_db)
    db_session.add(StreakEvent(
        user_id=user_id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=today,
        coins_delta=0,
        details={'source': 'linear_book_reading', 'book_id': book_id, 'xp': 15},
    ))
    db_session.commit()


def test_read_today_only_for_the_read_book(db_session, test_user):
    book_a, book_b = 90001, 90002  # arbitrary ids; signal 2 finds no sessions
    _add_reading_event(db_session, test_user.id, book_a)

    # Slot is done for the book actually read today …
    assert _read_today(test_user.id, book_a, app_db) is True
    # … but NOT for a different (newly-selected) book with no reading.
    assert _read_today(test_user.id, book_b, app_db) is False


def test_read_today_none_book_is_false(db_session, test_user):
    _add_reading_event(db_session, test_user.id, 90001)
    assert _read_today(test_user.id, None, app_db) is False


def test_legacy_event_without_book_id_does_not_close_slot(db_session, test_user):
    """Events written before the book_id detail must not blanket-close any book
    via signal 1 — they fall through to the book-specific time-gate (signal 2),
    which is False here (no reading sessions)."""
    today = get_linear_event_local_date(test_user.id, app_db)
    db_session.add(StreakEvent(
        user_id=test_user.id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=today,
        coins_delta=0,
        details={'source': 'linear_book_reading', 'xp': 15},  # no book_id
    ))
    db_session.commit()

    assert _read_today(test_user.id, 90001, app_db) is False
