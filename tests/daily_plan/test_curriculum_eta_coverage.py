"""Every curriculum lesson type must have an explicit dashboard ETA."""

from app.daily_plan.items.curriculum import _LESSON_ETA_MINUTES
from app.daily_plan.linear.xp import LESSON_TYPE_TO_SOURCE


def test_every_curriculum_lesson_type_has_explicit_eta():
    assert set(LESSON_TYPE_TO_SOURCE) <= set(_LESSON_ETA_MINUTES)
