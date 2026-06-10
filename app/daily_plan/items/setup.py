"""Setup item builders for the unified daily plan.

Setup items are skippable: they never appear in ``required`` and never block
``day_secured``. Two kinds are emitted:

- ``setup_book``  — user has not yet picked a book for reading. Disappears
  once a ``UserReadingPreference`` exists. After selection, the reading slot
  joins ``required`` only on the **next** day (today it joins ``optional``
  to avoid retroactively voiding an already-secured day).
- ``setup_level`` — user has no eligible curriculum content (empty level
  / all modules blocked by prereqs / bare catalogue). Points at the catalogue.

The orchestrator decides when each item is appropriate; this module only
builds them on demand.
"""
from __future__ import annotations

from typing import Any

from app.daily_plan.items import PlanItem


def build_setup_book_item() -> PlanItem:
    """Return a setup card prompting the user to pick a book.

    Stateless — call only when the user actually has no preference.
    """
    return PlanItem(
        id='setup:book',
        section='setup',
        kind='setup_book',
        title='Выбрать книгу',
        subtitle='Чтение появится в плане после выбора',
        lesson_type=None,
        eta_minutes=2,
        url='#book-select-modal',
        completed=False,
        completion_signal='setup_action',
        data={},
    )


def build_setup_level_item() -> PlanItem:
    """Return a setup card prompting the user to browse the catalogue.

    Emitted only when ``find_next_lesson_linear`` returns None AND the user
    has no completion history (no eligible content). Never confused with
    genuine course completion — that path emits a milestone, not a setup card.
    """
    return PlanItem(
        id='setup:level',
        section='setup',
        kind='setup_level',
        title='Открыть каталог курсов',
        subtitle='Подходящий уровень пока недоступен',
        lesson_type=None,
        eta_minutes=5,
        url='/learn/',
        completed=False,
        completion_signal='setup_action',
        data={},
    )


def book_selected_today(user_id: int, db: Any) -> bool:
    """Return True if the user picked a book today.

    Used by the orchestrator to decide whether a freshly-picked book joins
    optional (today) or required (tomorrow).
    """
    from app.daily_plan.linear.models import UserReadingPreference
    from app.utils.time_utils import get_user_local_day_bounds

    pref = (
        db.session.query(UserReadingPreference)
        .filter(UserReadingPreference.user_id == user_id)
        .first()
    )
    if pref is None or pref.selected_at is None:
        return False
    today_start, today_end = get_user_local_day_bounds(user_id, db)
    selected_at = pref.selected_at
    if selected_at.tzinfo is not None:
        # Границы — UTC-naive; aware-метку приводим к UTC, а не к локальной
        # зоне сервера (argless astimezone() сдвигал сравнение на offset хоста).
        from datetime import timezone
        selected_at = selected_at.astimezone(timezone.utc).replace(tzinfo=None)
    return today_start <= selected_at < today_end
