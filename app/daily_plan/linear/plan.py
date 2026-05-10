"""Linear daily plan assembly.

Assembles the linear-plan payload returned to dashboards/API when
``User.use_linear_plan`` is enabled: header position, level progress,
baseline slots (curriculum / SRS / reading / optional error review),
the continuation preview, and a ``day_secured`` flag derived from slot
completion. Each slot is computed at request time from authoritative
DB state; ``/api/daily-status`` then recomputes ``day_secured`` from
activity summaries (mirroring the mission flow) so that slot state
stays in sync with what the user has actually done today.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.auth.models import User
from app.curriculum.models import Lessons
from app.daily_plan.linear.progression import (
    LevelProgress,
    find_next_lesson_linear,
    get_spine_upcoming,
    get_user_level_progress,
)
from app.utils.db import db

VALID_FOCUSES = {'grammar', 'vocabulary', 'reading', 'all'}

SLOT_ESTIMATED_MINUTES: dict[str, int] = {
    'curriculum': 15,
    'srs': 10,
    'reading': 15,
    'listening': 10,
    'writing': 8,
    'error_review': 12,
}


def _get_user_focus(user_id: int, db_session: Any) -> Optional[str]:
    """Return the first onboarding-focus tag for the user, or None.

    ``User.onboarding_focus`` is stored as a comma-separated string of
    tags (one of ``grammar``/``vocabulary``/``reading``/``all``). Plan
    routing only uses the primary tag, so we split and return the first
    valid value. Unknown tags fall back to None to keep the plan in its
    standard shape.
    """
    user = db_session.session.get(User, user_id)
    if user is None:
        return None
    raw = getattr(user, 'onboarding_focus', None)
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    if not parts:
        return None
    primary = parts[0]
    if primary not in VALID_FOCUSES or primary == 'all':
        return None
    return primary

logger = logging.getLogger(__name__)


def compute_linear_day_secured(baseline_slots: list[dict[str, Any]]) -> bool:
    """Return True when every baseline slot is flagged completed.

    All slots in ``baseline_slots`` are required by construction — the
    error-review slot is appended only when ``should_show_error_review``
    fires, so its presence means the user must complete it to secure the
    day. When ``baseline_slots`` is empty (defensive: the assembler
    always returns at least curriculum / SRS / reading) the day is not
    secured.
    """
    if not baseline_slots:
        return False
    return all(bool(slot.get('completed', False)) for slot in baseline_slots)


def _level_progress_to_dict(progress: LevelProgress) -> dict[str, Any]:
    return {
        'level': progress.level,
        'percent': progress.percent,
        'lessons_remaining_in_level': progress.lessons_remaining_in_level,
    }


def _position_from_lesson(lesson: Any) -> Optional[dict[str, Any]]:
    if lesson is None:
        return None
    module = getattr(lesson, 'module', None)
    module_number = getattr(module, 'number', None)
    level = getattr(module, 'level', None) if module is not None else None
    level_code = getattr(level, 'code', None) if level is not None else None
    return {
        'lesson_id': lesson.id,
        'lesson_type': lesson.type,
        'lesson_number': lesson.number,
        'module_id': getattr(lesson, 'module_id', None),
        'module_number': module_number,
        'level_code': level_code,
    }


def _lesson_from_slot_data(slot_dict: dict[str, Any], db_session: Any) -> Optional[Lessons]:
    """Return the lesson referenced by a slot payload, if it still exists."""
    data = slot_dict.get('data') or {}
    lesson_id = data.get('lesson_id')
    if not lesson_id:
        return None
    try:
        return db_session.session.get(Lessons, int(lesson_id))
    except (TypeError, ValueError):
        return None


def get_linear_plan(
    user_id: int,
    db_session: Any = None,
) -> dict[str, Any]:
    """Return the linear daily plan payload.

    The linear plan is timezone-agnostic: slot builders read authoritative
    DB state (LessonProgress, UserChapterProgress, QuizErrorLog) and the
    API layer handles the user's local day when it recomputes
    ``day_secured``. No ``tz`` is needed here.
    """
    session_provider = db_session if db_session is not None else db

    logger.info("linear_plan_assemble user=%s start", user_id)

    next_lesson = find_next_lesson_linear(user_id, session_provider)
    level_progress = get_user_level_progress(user_id, session_provider, next_lesson=next_lesson)
    # The continuation preview must not duplicate what the inline chain
    # already shows: when day_secured is true the chain has a curriculum
    # extension pointing at next_lesson, and even before that the baseline
    # curriculum slot already represents next_lesson. Skip next_lesson and
    # fetch the lessons that come after it on the spine. Bot/dashboard
    # callers that need the next spine lesson directly read ``position``.
    upcoming = []
    if next_lesson is not None:
        upcoming = list(
            get_spine_upcoming(user_id, next_lesson, session_provider, limit=3)
        )

    focus = _get_user_focus(user_id, session_provider)

    logger.info(
        "linear_plan_assemble user=%s focus=%s level=%s level_pct=%d remaining=%d",
        user_id, focus or 'none',
        level_progress.level, level_progress.percent,
        level_progress.lessons_remaining_in_level,
    )

    from app.daily_plan.linear.chain import build_chain

    chain_result = build_chain(user_id, session_provider)
    all_slots = chain_result['slots']
    baseline_count = chain_result['baseline_count']
    baseline_slots = all_slots[:baseline_count]

    day_secured = compute_linear_day_secured(baseline_slots)

    slot_summary = " ".join(
        f"{s.get('kind')}={'done' if s.get('completed') else 'pending'}"
        for s in baseline_slots
    )
    logger.info(
        "linear_plan_assemble user=%s done slots=%d day_secured=%s [%s]",
        user_id, len(baseline_slots), day_secured, slot_summary,
    )

    from app.srs.counting import get_new_card_budget

    remaining_new, _remaining_reviews = get_new_card_budget(user_id, session_provider)
    srs_budget_exhausted = remaining_new <= 0

    total_estimated_minutes = sum(
        SLOT_ESTIMATED_MINUTES.get(slot.get('kind', ''), 0)
        for slot in all_slots
        if not slot.get('completed', False)
    )

    return {
        'mode': 'linear',
        'position': _position_from_lesson(next_lesson),
        'progress': _level_progress_to_dict(level_progress),
        'baseline_slots': baseline_slots,
        'slots': all_slots,
        'chain_meta': {
            'baseline_count': baseline_count,
            'has_more_available': chain_result['has_more_available'],
            'exhausted_sources': chain_result['exhausted_sources'],
        },
        'continuation': {
            'available': day_secured,
            'next_lessons': [_position_from_lesson(lesson) for lesson in upcoming],
            'srs_budget_exhausted': srs_budget_exhausted,
        },
        'day_secured': day_secured,
        'total_estimated_minutes': total_estimated_minutes,
    }
