"""Canonical curriculum navigation.

Single source of truth for "what is the user's next lesson?" across the
product. Linear daily plan, mission assembler, and curriculum dashboards
all delegate here so a user sees a consistent next-lesson regardless of
surface.

The canonical algorithm is the monotonic spine defined in
`app/daily_plan/linear/progression.py:find_next_lesson_linear` — ordered
by (CEFRLevel.order, Module.number, Lessons.number), filtered by the
user's onboarding level, and gated on `Module.check_prerequisites` so
locked modules (e.g. a checkpoint that the user has not passed) are
skipped rather than silently unlocked.
"""
from __future__ import annotations

from typing import Any, Optional

from app.curriculum.models import Lessons
from app.daily_plan.linear.progression import find_next_lesson_linear


def find_next_lesson(user_id: int, db: Any) -> Optional[Lessons]:
    """Return the user's canonical next lesson.

    Thin wrapper around `find_next_lesson_linear` so callers that do not
    otherwise depend on the linear daily-plan package can import a stable
    top-level function. The return value is a `Lessons` ORM object or
    `None` when nothing eligible remains.
    """
    return find_next_lesson_linear(user_id, db)
