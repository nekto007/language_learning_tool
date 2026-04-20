"""Linear daily plan XP integration helpers.

Thin adapter layer between the slot-completion endpoints (curriculum
lesson grading, SRS session complete, book reading progress, error review)
and the shared XP service. Responsibilities:

- Map curriculum ``Lesson.type`` values onto the ``LINEAR_XP`` source keys.
- Gate awards on ``User.use_linear_plan`` so mission-flow users are never
  double-credited with both phase and linear XP.
- Persist one ``StreakEvent(event_type='xp_linear')`` per user+date+source
  so repeated grade submissions are idempotent for the day.
- Trigger the linear perfect-day bonus once all baseline slots complete.

The caller owns the outer transaction: these helpers flush but never
commit, matching the grading / SRS / reading endpoints that wrap their
mutations in a single commit.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls, datetime, timezone
from typing import Any, Optional

from app.achievements.xp_service import (
    LINEAR_XP,
    XPAward,
    award_linear_xp,
    award_perfect_day_xp_idempotent,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mapping: curriculum lesson.type → LINEAR_XP source key.
# Legacy aliases ("matching", "text", "flashcards") collapse onto the
# closest canonical source so older content still earns XP.
# ---------------------------------------------------------------------------
LESSON_TYPE_TO_SOURCE: dict[str, str] = {
    'card': 'linear_curriculum_card',
    'flashcards': 'linear_curriculum_card',
    'vocabulary': 'linear_curriculum_vocabulary',
    'grammar': 'linear_curriculum_grammar',
    'quiz': 'linear_curriculum_quiz',
    'listening_quiz': 'linear_curriculum_listening_quiz',
    'dialogue_completion_quiz': 'linear_curriculum_dialogue_completion_quiz',
    'ordering_quiz': 'linear_curriculum_ordering_quiz',
    'translation_quiz': 'linear_curriculum_translation_quiz',
    'final_test': 'linear_curriculum_final_test',
    'reading': 'linear_curriculum_reading',
    'text': 'linear_curriculum_reading',
    'listening_immersion': 'linear_curriculum_listening_immersion',
    'listening_immersion_quiz': 'linear_curriculum_listening_immersion',
    'matching': 'linear_curriculum_quiz',
}

LINEAR_XP_EVENT_TYPE = 'xp_linear'


def _today_utc() -> date_cls:
    return datetime.now(timezone.utc).date()


def is_linear_user(user_id: int) -> bool:
    """Return True when the user has the linear plan flag enabled."""
    from app.auth.models import User
    from app.utils.db import db

    user = db.session.get(User, user_id)
    if user is None:
        return False
    return bool(getattr(user, 'use_linear_plan', False))


def get_source_for_lesson_type(lesson_type: Optional[str]) -> Optional[str]:
    """Return the ``LINEAR_XP`` source key for a curriculum lesson type.

    Returns ``None`` for unknown or missing types — callers should skip
    the XP award rather than raise.
    """
    if not lesson_type:
        return None
    return LESSON_TYPE_TO_SOURCE.get(lesson_type)


def _already_awarded(
    user_id: int, source: str, for_date: date_cls, db_session: Any
) -> bool:
    from app.achievements.models import StreakEvent

    query = db_session.session.query(StreakEvent).filter(
        StreakEvent.user_id == user_id,
        StreakEvent.event_type == LINEAR_XP_EVENT_TYPE,
        StreakEvent.event_date == for_date,
        StreakEvent.details['source'].astext == source,
    )
    return db_session.session.query(query.exists()).scalar() or False


def award_linear_slot_xp_idempotent(
    user_id: int,
    source: str,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP once per (user, date, source).

    Returns the ``XPAward`` on first call for that tuple, ``None`` on
    subsequent calls the same day. Caller owns the commit.
    """
    if source not in LINEAR_XP:
        logger.warning('linear_xp: unknown source %r for user=%s', source, user_id)
        return None

    from app.achievements.models import StreakEvent
    from app.utils.db import db

    db_obj = db_session if db_session is not None else db
    when = for_date or _today_utc()

    if _already_awarded(user_id, source, when, db_obj):
        return None

    result = award_linear_xp(user_id, source)
    db_obj.session.add(StreakEvent(
        user_id=user_id,
        event_type=LINEAR_XP_EVENT_TYPE,
        event_date=when,
        coins_delta=0,
        details={'source': source, 'xp': result.xp_awarded},
    ))
    db_obj.session.flush()
    return result


def maybe_award_curriculum_xp(
    user_id: int,
    lesson: Any,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP for a completed curriculum lesson.

    Silent no-op when the user is not on the linear plan, the lesson
    type has no registered source, or the award was already recorded
    for today.
    """
    if not is_linear_user(user_id):
        return None

    source = get_source_for_lesson_type(getattr(lesson, 'type', None))
    if source is None:
        return None

    return award_linear_slot_xp_idempotent(user_id, source, for_date, db_session)


def maybe_award_srs_global_xp(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP for completing a /study SRS session."""
    if not is_linear_user(user_id):
        return None
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_srs_global', for_date, db_session,
    )


def maybe_award_book_reading_xp(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP when the reading slot completes for the day.

    Called once per day regardless of how many chapters the user
    advances — the slot itself only flips to ``completed=True`` when the
    ``UserChapterProgress`` delta crosses ``READ_PROGRESS_THRESHOLD``.
    """
    if not is_linear_user(user_id):
        return None
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_book_reading', for_date, db_session,
    )


def maybe_award_error_review_xp(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award linear XP for completing an error-review session."""
    if not is_linear_user(user_id):
        return None
    return award_linear_slot_xp_idempotent(
        user_id, 'linear_error_review', for_date, db_session,
    )


def maybe_award_linear_perfect_day(
    user_id: int,
    for_date: Optional[date_cls] = None,
    db_session: Any = None,
) -> Optional[XPAward]:
    """Award the linear perfect-day bonus when all baseline slots are done.

    Completion detection mirrors ``/api/daily-status``: we combine each
    slot's own ``completed`` flag with the daily activity summary so a
    user who completed today's work earns the bonus even though the
    per-slot ``completed`` field tracks the next incomplete target
    (e.g., the curriculum slot always points at the next unfinished
    lesson). Without this, the perfect-day bonus would almost never
    fire since the slot-builder's ``completed`` field is rarely True
    for the current day's activity.
    """
    if not is_linear_user(user_id):
        return None

    from app.achievements.streak_service import compute_plan_steps
    from app.daily_plan.linear.plan import get_linear_plan
    from app.telegram.queries import get_daily_summary

    when = for_date or _today_utc()

    try:
        plan = get_linear_plan(user_id, db_session)
        summary = get_daily_summary(user_id)
    except Exception:  # noqa: BLE001 — never break caller on plan assembly
        logger.warning(
            'linear_xp: perfect-day check failed to assemble plan for user=%s',
            user_id, exc_info=True,
        )
        return None

    baseline_slots = plan.get('baseline_slots') or []
    if not baseline_slots:
        return None

    plan_completion, _, _, _ = compute_plan_steps(plan, summary)
    all_done = all(
        plan_completion.get(slot.get('kind', ''), False)
        for slot in baseline_slots
    )
    if not all_done:
        return None

    return award_perfect_day_xp_idempotent(user_id, when, is_linear=True)
