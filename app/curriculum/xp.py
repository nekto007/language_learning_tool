"""Curriculum lesson XP idempotency helper.

Prevents duplicate XP awards when ``complete_lesson`` is invoked more than
once for the same user/lesson/day (e.g. page reload, client retry, or the
callsite is reached twice in the same flow). Uses ``StreakEvent`` with
``event_type='xp_curriculum_lesson'`` as the dedup ledger, matching the
pattern used by ``award_phase_xp_idempotent`` / linear slot XP helpers.

Callers own the outer commit; this helper only flushes the StreakEvent
row so the dedup check is visible to a subsequent call inside the same
transaction.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls
from typing import Any, Optional

from app.achievements.xp_service import XPAward, award_xp

logger = logging.getLogger(__name__)

CURRICULUM_LESSON_XP = 30
CURRICULUM_LESSON_EVENT_TYPE = 'xp_curriculum_lesson'


def award_curriculum_lesson_xp_idempotent(
    user_id: int,
    lesson_id: int,
    for_date: date_cls,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award curriculum-lesson XP once per (user, lesson, date).

    Returns the ``XPAward`` on first call for that tuple, ``None`` on
    subsequent calls for the same day.
    """
    from app.achievements.models import StreakEvent
    from app.utils.db import db

    db_obj = db_session if db_session is not None else db

    already = db_obj.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == CURRICULUM_LESSON_EVENT_TYPE,
        StreakEvent.event_date == for_date,
        StreakEvent.details['lesson_id'].astext == str(lesson_id),
    ).first()
    if already is not None:
        return None

    result = award_xp(user_id, CURRICULUM_LESSON_XP, 'curriculum_lesson')

    db_obj.session.add(StreakEvent(
        user_id=user_id,
        event_type=CURRICULUM_LESSON_EVENT_TYPE,
        event_date=for_date,
        coins_delta=0,
        details={'lesson_id': lesson_id, 'xp': result.xp_awarded},
    ))
    db_obj.session.flush()
    return result
