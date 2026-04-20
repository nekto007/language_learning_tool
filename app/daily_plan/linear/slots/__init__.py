"""Baseline slot builders for the linear daily plan.

Each slot module exposes a ``build_<kind>_slot(user_id, db, ...)`` function
that returns a ``LinearSlot`` describing a single baseline activity shown
on the dashboard: the next curriculum lesson, SRS global review, chosen
book reading, or the optional error-review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class LinearSlot:
    """A single dashboard baseline slot for the linear daily plan."""

    kind: str
    title: str
    lesson_type: Optional[str]
    eta_minutes: int
    url: Optional[str]
    completed: bool
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'kind': self.kind,
            'title': self.title,
            'lesson_type': self.lesson_type,
            'eta_minutes': self.eta_minutes,
            'url': self.url,
            'completed': self.completed,
            'data': dict(self.data),
        }
