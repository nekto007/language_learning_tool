from __future__ import annotations

import enum
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, Date, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.utils.db import db
from app.utils.types import JSONBCompat

logger = logging.getLogger(__name__)


class DailyPlanLog(db.Model):
    """One row per user per calendar day recording mission selection and secured state."""
    __tablename__ = 'daily_plan_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    plan_date = Column(Date, nullable=False)
    mission_type = Column(String(20), nullable=True)
    secured_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship('User', backref='daily_plan_logs')

    __table_args__ = (
        UniqueConstraint('user_id', 'plan_date', name='uq_daily_plan_log_user_date'),
        Index('idx_daily_plan_log_user_date', 'user_id', 'plan_date'),
    )


class MissionType(enum.Enum):
    """progress = advance in primary course, repair = fix weak spots (SRS/grammar), reading = book-first session."""
    progress = "progress"
    repair = "repair"
    reading = "reading"


class PhaseKind(enum.Enum):
    """Canonical learning phases: recall → learn → use/read → check/close → bonus."""
    recall = "recall"
    learn = "learn"
    use = "use"
    read = "read"
    check = "check"
    close = "close"
    bonus = "bonus"


class SourceKind(enum.Enum):
    normal_course = "normal_course"
    book_course = "book_course"
    books = "books"
    srs = "srs"
    grammar_lab = "grammar_lab"
    vocab = "vocab"


# Central registry: every mission-plan mode → its activity category.
# Used by streak_service (completion checks) and routes (URL grouping).
MODE_CATEGORY_MAP: dict[str, str] = {
    'srs_review': 'words',
    'guided_recall': 'words',
    'book_vocab_recall': 'words',
    'micro_check': 'words',
    'meaning_prompt': 'words',
    'vocab_drill': 'words',
    'reading_vocab_extract': 'words',
    'curriculum_lesson': 'lesson',
    'lesson_practice': 'lesson',
    'book_course_lesson': 'book_course',
    'book_course_practice': 'book_course',
    'grammar_practice': 'grammar',
    'targeted_quiz': 'grammar',
    'book_reading': 'books',
    'success_marker': 'meta',
    'fun_fact_quiz': 'bonus',
    'speed_review': 'bonus',
    'word_scramble': 'bonus',
}


@dataclass
class PhasePreview:
    """Preview metadata shown to the user before starting a phase."""
    item_count: Optional[int] = None
    content_title: Optional[str] = None
    estimated_minutes: Optional[int] = None


@dataclass
class MissionPhase:
    phase: PhaseKind
    title: str
    source_kind: SourceKind
    mode: str
    required: bool = True
    completed: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    preview: Optional[PhasePreview] = None


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
    """Top-level daily plan: 1 mission + 1 source + 3-4 sequential phases. Legacy dict preserves backward compat."""
    plan_version: str
    mission: Mission
    primary_goal: PrimaryGoal
    primary_source: PrimarySource
    phases: list[MissionPhase]
    completion: Optional[dict[str, Any]] = None
    legacy: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not isinstance(self.phases, list) or not (3 <= len(self.phases) <= 5):
            raise ValueError(
                f"MissionPlan requires 3-5 phases, got {len(self.phases) if isinstance(self.phases, list) else 'non-list'}"
            )
        if not isinstance(self.mission, Mission):
            raise TypeError("mission must be a Mission instance")
        if not isinstance(self.primary_goal, PrimaryGoal):
            raise TypeError("primary_goal must be a PrimaryGoal instance")
        if not isinstance(self.primary_source, PrimarySource):
            raise TypeError("primary_source must be a PrimarySource instance")

        # Warn only for suspicious duplicate categories. Some mission flows
        # intentionally reuse a category for distinct steps, for example:
        # curriculum lesson -> lesson practice, or SRS recall -> micro check.
        skip_dup_warning = self.mission.type == MissionType.reading
        _EXEMPT_CATEGORIES = {'bonus', 'meta'}
        _ALLOWED_DUPLICATE_MODE_PAIRS = {
            frozenset({'curriculum_lesson', 'lesson_practice'}),
            frozenset({'book_course_lesson', 'book_course_practice'}),
            frozenset({'srs_review', 'micro_check'}),
        }
        seen_categories: dict[str, int] = {}
        for i, phase in enumerate(self.phases):
            cat = MODE_CATEGORY_MAP.get(phase.mode)
            if cat is not None and cat in seen_categories and not skip_dup_warning and cat not in _EXEMPT_CATEGORIES:
                previous_phase = self.phases[seen_categories[cat]]
                allowed_pair = frozenset({previous_phase.mode, phase.mode}) in _ALLOWED_DUPLICATE_MODE_PAIRS
                if allowed_pair:
                    continue
                logger.warning(
                    "MissionPlan duplicate category %r in phases[%d] (mode=%s) "
                    "and phases[%d] (mode=%s)",
                    cat, seen_categories[cat], previous_phase.mode,
                    i, phase.mode,
                )
            elif cat is not None:
                seen_categories[cat] = i
