"""Timezone helpers shared across XP idempotency write-paths.

Both the curriculum-lesson path (``complete_lesson`` in
``app/curriculum/service.py``) and the linear/card-lesson path
(``complete_srs_session`` → ``maybe_award_curriculum_xp``) dedupe XP by
``(user_id, local_date, lesson_id)``. If the two paths resolve the local
date differently, a user finishing a lesson near midnight can be awarded
XP twice — once under the UTC date and once under the user's tz date.

``get_user_local_date`` is the single source of truth: read
``User.timezone`` (falling back to ``config.settings.DEFAULT_TIMEZONE``
then UTC) and return ``datetime.now(tz).date()``.
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, timezone
from typing import Any, Optional


def get_user_local_date(
    user_id: int,
    db_session: Any = None,
) -> date_cls:
    """Return today's date in the user's timezone.

    Falls back to ``config.settings.DEFAULT_TIMEZONE`` when the user has
    no timezone set, and to UTC if that value fails to resolve (e.g. on
    a malformed override).
    """
    from zoneinfo import ZoneInfo

    from app.auth.models import User
    from app.utils.db import db
    from config.settings import DEFAULT_TIMEZONE

    db_obj = db_session if db_session is not None else db
    user = db_obj.session.get(User, user_id)
    tz_name: Optional[str] = getattr(user, 'timezone', None) or DEFAULT_TIMEZONE
    try:
        tz_obj = ZoneInfo(tz_name)
    except Exception:
        tz_obj = timezone.utc
    return datetime.now(tz_obj).date()
