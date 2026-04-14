from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


class MissionType(enum.Enum):
    progress = "progress"
    repair = "repair"
    reading = "reading"


class PhaseKind(enum.Enum):
    recall = "recall"
    learn = "learn"
    use = "use"
    read = "read"
    check = "check"
    close = "close"


class SourceKind(enum.Enum):
    normal_course = "normal_course"
    book_course = "book_course"
    books = "books"
    srs = "srs"
    grammar_lab = "grammar_lab"
    vocab = "vocab"


@dataclass
class MissionPhase:
    phase: PhaseKind
    title: str
    source_kind: SourceKind
    mode: str
    required: bool = True
    completed: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class Mission:
    type: MissionType
    title: str
    reason_code: str
    reason_text: str


@dataclass
class PrimaryGoal:
    type: str
    title: str
    success_criterion: str


@dataclass
class PrimarySource:
    kind: SourceKind
    id: Optional[str]
    label: str


@dataclass
class MissionPlan:
    plan_version: str
    mission: Mission
    primary_goal: PrimaryGoal
    primary_source: PrimarySource
    phases: list[MissionPhase]
    completion: Optional[dict[str, Any]] = None
    legacy: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.phases, list) or not (3 <= len(self.phases) <= 4):
            raise ValueError(
                f"MissionPlan requires 3-4 phases, got {len(self.phases) if isinstance(self.phases, list) else 'non-list'}"
            )
        if not isinstance(self.mission, Mission):
            raise TypeError("mission must be a Mission instance")
        if not isinstance(self.primary_goal, PrimaryGoal):
            raise TypeError("primary_goal must be a PrimaryGoal instance")
        if not isinstance(self.primary_source, PrimarySource):
            raise TypeError("primary_source must be a PrimarySource instance")
