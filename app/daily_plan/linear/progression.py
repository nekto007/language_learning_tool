"""Linear progression helpers for the linear daily plan.

Provides curriculum navigation as a single monotonic spine ordered by
(CEFRLevel.order, Module.number, Lessons.number), filtered so the user
never regresses below their onboarding_level.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import case, func

from app.auth.models import User
from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.level_utils import _cefr_code_to_order

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LevelProgress:
    """User progress snapshot for the CEFR level they are currently on."""

    level: str
    percent: int
    lessons_remaining_in_level: int


def _user_min_level_order(user_id: int, db: Any) -> int:
    """Return the lowest CEFRLevel.order the user is allowed to see.

    Uses User.onboarding_level when present; otherwise returns 0 so every
    level is eligible. A missing/unknown onboarding code also yields 0.
    """
    user = db.session.get(User, user_id)
    if not user or not user.onboarding_level:
        return 0
    order = _cefr_code_to_order(user.onboarding_level, db)
    return max(order, 0)


def find_next_lesson_linear(user_id: int, db: Any) -> Optional[Lessons]:
    """Return the next incomplete lesson on the linear curriculum spine.

    Lessons are ordered by (CEFRLevel.order, Module.number, Lessons.number).
    Anything whose level is below the user's onboarding level is skipped.
    Any module whose prerequisites are not satisfied for the user is skipped
    so users cannot bypass checkpoints by URL manipulation — if that leaves
    nothing accessible, returns None.

    Returns None when the user has completed every eligible lesson.
    """
    min_order = _user_min_level_order(user_id, db)

    completed_subq = (
        db.session.query(LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        )
        .subquery()
    )

    candidates = (
        db.session.query(Lessons)
        .join(Module, Module.id == Lessons.module_id)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .filter(
            CEFRLevel.order >= min_order,
            Lessons.id.notin_(db.session.query(completed_subq.c.lesson_id)),
        )
        .order_by(
            CEFRLevel.order.asc(),
            Module.number.asc(),
            Lessons.number.asc(),
            Lessons.id.asc(),
        )
    )

    module_access: dict[int, bool] = {}
    for lesson in candidates:
        module_id = lesson.module_id
        accessible = module_access.get(module_id)
        if accessible is None:
            module = db.session.get(Module, module_id)
            accessible = True
            if module is not None:
                ok, _reasons = module.check_prerequisites(user_id)
                accessible = bool(ok)
            module_access[module_id] = accessible
        if accessible:
            return lesson
    return None


def get_user_level_progress(
    user_id: int,
    db: Any,
    next_lesson: Optional[Lessons] = None,
) -> LevelProgress:
    """Return current-level progress metrics for the linear dashboard.

    "Current level" is the level of the next lesson returned by
    find_next_lesson_linear. When the user has completed everything,
    fall back to the highest eligible level and report it fully complete.

    ``next_lesson`` may be passed by the plan assembler to avoid a second
    DB round-trip when it already resolved the next lesson.
    """
    min_order = _user_min_level_order(user_id, db)

    if next_lesson is None:
        next_lesson = find_next_lesson_linear(user_id, db)

    if next_lesson is not None:
        module = db.session.get(Module, next_lesson.module_id)
        current_level = db.session.get(CEFRLevel, module.level_id) if module else None
    else:
        current_level = (
            db.session.query(CEFRLevel)
            .filter(CEFRLevel.order >= min_order)
            .order_by(CEFRLevel.order.desc())
            .first()
        )

    if current_level is None:
        return LevelProgress(
            level='',
            percent=0,
            lessons_remaining_in_level=0,
        )

    total_in_level, completed_in_level = (
        db.session.query(
            func.count(Lessons.id),
            func.sum(
                case(
                    (LessonProgress.status == 'completed', 1),
                    else_=0,
                )
            ),
        )
        .select_from(Lessons)
        .join(Module, Module.id == Lessons.module_id)
        .outerjoin(
            LessonProgress,
            (LessonProgress.lesson_id == Lessons.id)
            & (LessonProgress.user_id == user_id),
        )
        .filter(Module.level_id == current_level.id)
        .one()
    )
    total_in_level = int(total_in_level or 0)
    completed_in_level = int(completed_in_level or 0)

    remaining_in_level = max(total_in_level - completed_in_level, 0)
    percent = int(round(completed_in_level * 100 / total_in_level)) if total_in_level else 0

    return LevelProgress(
        level=current_level.code,
        percent=percent,
        lessons_remaining_in_level=remaining_in_level,
    )


def get_module_upcoming(
    user_id: int,
    current_lesson: Lessons,
    db: Any,
    limit: int = 3,
) -> list[Lessons]:
    """Return the next ``limit`` lessons after ``current_lesson`` within the module.

    Does not cross module boundaries — continuation preview is module-local.
    Already-completed lessons are excluded so the preview shows work the
    user has not done yet.
    """
    if current_lesson is None or limit <= 0:
        return []

    completed_subq = (
        db.session.query(LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        )
        .subquery()
    )

    return (
        db.session.query(Lessons)
        .filter(
            Lessons.module_id == current_lesson.module_id,
            Lessons.number > current_lesson.number,
            Lessons.id.notin_(db.session.query(completed_subq.c.lesson_id)),
        )
        .order_by(Lessons.number.asc(), Lessons.id.asc())
        .limit(limit)
        .all()
    )


def get_spine_upcoming(
    user_id: int,
    current_lesson: Lessons,
    db: Any,
    limit: int = 3,
) -> list[Lessons]:
    """Return the next incomplete lessons on the full curriculum spine.

    Used by the continuation CTA. Unlike ``get_module_upcoming()``, this may
    cross module and level boundaries so a user who finishes the last lesson
    in one module still gets the first lesson of the next module.
    """
    if current_lesson is None or limit <= 0:
        return []

    min_order = _user_min_level_order(user_id, db)
    current_module = db.session.get(Module, current_lesson.module_id)
    if current_module is None:
        return []
    current_level = db.session.get(CEFRLevel, current_module.level_id)
    if current_level is None:
        return []

    completed_subq = (
        db.session.query(LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        )
        .subquery()
    )

    return (
        db.session.query(Lessons)
        .join(Module, Module.id == Lessons.module_id)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .filter(
            CEFRLevel.order >= min_order,
            Lessons.id.notin_(db.session.query(completed_subq.c.lesson_id)),
            (
                (CEFRLevel.order > current_level.order)
                | (
                    (CEFRLevel.order == current_level.order)
                    & (Module.number > current_module.number)
                )
                | (
                    (CEFRLevel.order == current_level.order)
                    & (Module.number == current_module.number)
                    & (Lessons.number > current_lesson.number)
                )
            ),
        )
        .order_by(
            CEFRLevel.order.asc(),
            Module.number.asc(),
            Lessons.number.asc(),
            Lessons.id.asc(),
        )
        .limit(limit)
        .all()
    )
