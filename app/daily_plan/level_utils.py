# app/daily_plan/level_utils.py

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _cefr_code_to_order(level_code: str, db) -> int:
    """Return CEFRLevel.order for the given code, or -1 if not found."""
    from app.curriculum.models import CEFRLevel

    if not level_code:
        return -1
    row = db.session.query(CEFRLevel.order).filter(CEFRLevel.code == level_code).first()
    if row is None:
        logger.warning("CEFRLevel not found for code=%s", level_code)
        return -1
    return row[0]


def get_user_current_cefr_level(user_id: int, db) -> str:
    """
    Derive the effective CEFR level for a user.

    Compares:
    - Highest CEFRLevel reached via completed lesson progress
    - User.onboarding_level (set during onboarding survey)

    Returns the code of whichever level has the higher CEFRLevel.order.
    Falls back to 'A0' when both are absent or unresolvable.
    """
    from app.auth.models import User
    from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

    # --- progress-based level ---
    progress_order: int = -1
    progress_code: str | None = None

    row = (
        db.session.query(CEFRLevel.order, CEFRLevel.code)
        .join(Module, Module.level_id == CEFRLevel.id)
        .join(Lessons, Lessons.module_id == Module.id)
        .join(LessonProgress, LessonProgress.lesson_id == Lessons.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == "completed",
        )
        .order_by(CEFRLevel.order.desc())
        .first()
    )
    if row is not None:
        progress_order, progress_code = row[0], row[1]

    # --- onboarding-based level ---
    onboarding_order: int = -1
    onboarding_code: str | None = None

    user = db.session.get(User, user_id)
    if user and user.onboarding_level:
        onboarding_order = _cefr_code_to_order(user.onboarding_level, db)
        if onboarding_order >= 0:
            onboarding_code = user.onboarding_level

    # --- pick higher ---
    if progress_order >= onboarding_order and progress_code is not None:
        return progress_code
    if onboarding_code is not None:
        return onboarding_code

    return "A0"
