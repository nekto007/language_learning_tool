"""One definition of "today" for tests that seed relative dates.

The app's day is a *study day*: it starts at 02:00 local, not at midnight
(``LEARNING_DAY_START_HOUR`` in ``app/utils/time_utils.py``). That is a
deliberate product decision — a session started late at night must not have
its plan, streak, SRS budget or reading target reset out from under it.

``date.today()`` is the calendar date, which disagrees with the study day
between local midnight and 02:00. Tests that seeded "N days ago" with
``date.today()`` while production compared against ``get_user_local_date``
were therefore off by exactly one day during those two hours — and those are
precisely the hours the app is built for, so the suite failed nightly.

Seed dates with :func:`study_today` instead, so tests and production agree by
construction rather than by coincidence.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional


def study_today(user_id: Optional[int] = None, db_session: Any = None) -> date:
    """Return "today" on the same basis the application uses.

    Delegates to the production helper, so the 02:00 boundary can never drift
    between the two. ``user_id=None`` resolves the timezone the same way an
    unconfigured user does (``DEFAULT_TIMEZONE``), which is what test users
    without an explicit timezone get.
    """
    from app.utils.time_utils import get_user_local_date

    return get_user_local_date(user_id, db_session)
