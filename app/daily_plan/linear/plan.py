"""Linear daily plan assembly.

Stub for the linear-plan payload returned to dashboards/API when
``User.use_linear_plan`` is enabled. Baseline slots, continuation data,
and day-secured evaluation are filled in by subsequent tasks — this
module currently returns a stable skeleton so the router can wire up.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.linear.progression import (
    LevelProgress,
    find_next_lesson_linear,
    get_module_upcoming,
    get_user_level_progress,
)
from app.daily_plan.linear.slots.curriculum_slot import build_curriculum_slot
from app.utils.db import db

logger = logging.getLogger(__name__)


def _level_progress_to_dict(progress: LevelProgress) -> dict[str, Any]:
    return {
        'level': progress.level,
        'percent': progress.percent,
        'lessons_remaining_in_level': progress.lessons_remaining_in_level,
        'lessons_remaining_to_next_level': progress.lessons_remaining_to_next_level,
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
    tz: Optional[str] = None,
) -> dict[str, Any]:
    """Return the linear daily plan skeleton.

    Baseline slots, continuation payload, and day_secured evaluation will be
    filled in by later tasks — for now we return enough structure so the
    router, API layer, and dashboard can integrate against a stable shape.
    """
    session_provider = db_session if db_session is not None else db

    next_lesson = find_next_lesson_linear(user_id, session_provider)
    level_progress = get_user_level_progress(user_id, session_provider)
    upcoming = (
        get_module_upcoming(user_id, next_lesson, session_provider, limit=3)
        if next_lesson is not None
        else []
    )

    curriculum_slot = build_curriculum_slot(user_id, session_provider, next_lesson=next_lesson)

    return {
        'mode': 'linear',
        'position': _position_from_lesson(next_lesson),
        'progress': _level_progress_to_dict(level_progress),
        'baseline_slots': [curriculum_slot.to_dict()],
        'continuation': {
            'available': False,
            'next_lessons': [_position_from_lesson(lesson) for lesson in upcoming],
        },
        'day_secured': False,
    }
