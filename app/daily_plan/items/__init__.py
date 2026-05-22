"""PlanItem dataclass and section/kind taxonomy for the unified daily plan.

A PlanItem is a single actionable card shown to the user. The unified plan
groups items into three sections:

- ``required``  — the minimum learning work that closes the day. ``day_secured``
  is computed from this section only.
- ``optional``  — bonus work after the minimum. Items earn XP and route progress
  but never block ``day_secured``.
- ``setup``     — non-blocking preparation steps (pick a book, choose a level).
  Skippable. When the user completes a setup action mid-day, the corresponding
  learning slot is unlocked for the next day (never retroactively in required).

Milestone events (day/module/level/book completed) are emitted off-band via the
Notification mechanism and never appear in the plan payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

Section = Literal['required', 'optional', 'setup']

Kind = Literal[
    'curriculum',
    'srs',
    'reading',
    'listening',
    'speaking',
    'writing',
    'error_review',
    'challenge',
    'setup_book',
    'setup_level',
]

CompletionSignal = Literal[
    'lesson_completed',
    'srs_xp_earned',
    'reading_gate',
    'writing_attempt',
    'listening_attempt',
    'pronunciation_attempt',
    'error_review_done',
    'challenge_completed',
    'setup_action',
    'none',
]


@dataclass(frozen=True)
class PlanItem:
    """One actionable card in the unified daily plan."""

    id: str
    section: Section
    kind: Kind
    title: str
    eta_minutes: int
    completed: bool
    completion_signal: CompletionSignal
    subtitle: Optional[str] = None
    lesson_type: Optional[str] = None
    url: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'section': self.section,
            'kind': self.kind,
            'title': self.title,
            'subtitle': self.subtitle,
            'lesson_type': self.lesson_type,
            'eta_minutes': self.eta_minutes,
            'url': self.url,
            'completed': self.completed,
            'completion_signal': self.completion_signal,
            'data': dict(self.data),
        }
