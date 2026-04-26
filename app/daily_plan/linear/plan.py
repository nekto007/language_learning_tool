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
from app.daily_plan.linear.progression import (
    LevelProgress,
    find_next_lesson_linear,
    get_spine_upcoming,
    get_user_level_progress,
)
from app.daily_plan.linear.slots.curriculum_slot import build_curriculum_slot
from app.daily_plan.linear.slots.error_review_slot import build_error_review_slot
from app.daily_plan.linear.slots.reading_slot import build_reading_slot
from app.daily_plan.linear.slots.srs_slot import build_srs_slot
from app.utils.db import db

VALID_FOCUSES = {'grammar', 'vocabulary', 'reading', 'all'}


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

    next_lesson = find_next_lesson_linear(user_id, session_provider)
    level_progress = get_user_level_progress(user_id, session_provider, next_lesson=next_lesson)
    upcoming = []
    if next_lesson is not None:
        upcoming = [next_lesson]
        upcoming.extend(
            get_spine_upcoming(user_id, next_lesson, session_provider, limit=2)
        )

    focus = _get_user_focus(user_id, session_provider)

    curriculum_slot = build_curriculum_slot(user_id, session_provider, next_lesson=next_lesson)
    srs_slot = build_srs_slot(user_id, session_provider, curriculum_lesson=next_lesson)
    reading_slot = build_reading_slot(user_id, session_provider, focus=focus)
    error_review_slot = build_error_review_slot(user_id, session_provider)

    curriculum_dict = curriculum_slot.to_dict()
    srs_dict = srs_slot.to_dict()
    reading_dict = reading_slot.to_dict()

    if focus == 'grammar':
        curriculum_dict['data']['prioritize_grammar'] = True

    if focus == 'reading':
        # Reading-focused users see the reading slot promoted to position 2
        # (curriculum stays first as the spine anchor).
        baseline_slots = [curriculum_dict, reading_dict, srs_dict]
    else:
        baseline_slots = [curriculum_dict, srs_dict, reading_dict]
    if error_review_slot is not None:
        baseline_slots.append(error_review_slot.to_dict())

    day_secured = compute_linear_day_secured(baseline_slots)

    return {
        'mode': 'linear',
        'position': _position_from_lesson(next_lesson),
        'progress': _level_progress_to_dict(level_progress),
        'baseline_slots': baseline_slots,
        'continuation': {
            'available': day_secured,
            'next_lessons': [_position_from_lesson(lesson) for lesson in upcoming],
        },
        'day_secured': day_secured,
    }
