"""Path-progression dashboard view helpers.

Powers the redesigned ``/dashboard`` (path-style per-module view). The
canonical "current module" is the module that owns the user's next
incomplete lesson on the linear spine. If the user has finished every
eligible lesson, the most recently completed module is shown so the
dashboard never goes blank.

``build_path_nodes`` walks the lessons of the chosen module and emits
one node per lesson with display state (done / current / locked / open),
plus the cosmetic horizontal offset used by the templates to break the
straight column into a soft path.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.progression import find_next_lesson_linear

logger = logging.getLogger(__name__)


# Iconography for the path nodes.  Deliberately generic, single-glyph
# emoji to keep the look distinct from Duolingo (no owl, no skill
# crystals).  Templates may swap these for SVG later — the key is that
# the icon comes from a server-resolved type, not from a CSS class
# fingerprint.
LESSON_TYPE_ICONS: dict[str, str] = {
    'vocabulary': '📚',
    'card': '🃏',
    'flashcards': '🃏',
    'anki_cards': '🃏',
    'grammar': '✏️',
    'quiz': '🎯',
    'listening_quiz': '🎧',
    'dialogue_completion_quiz': '💬',
    'ordering_quiz': '🔀',
    'translation_quiz': '🌐',
    'reading': '📖',
    'text': '📖',
    'listening_immersion': '🎧',
    'dictation': '📝',
    'audio_fill_blank': '🎧',
    'shadow_reading': '🗣️',
    'translation': '🌐',
    'sentence_correction': '✏️',
    'sentence_completion': '✏️',
    'collocation_matching': '🔗',
    'writing_prompt': '✍️',
    'pronunciation': '🎤',
    'idiom': '💡',
    'matching': '🧩',
    'final_test': '🏁',
}
DEFAULT_LESSON_ICON = '🎓'

# Horizontal offset pattern (px). 5-step soft zig-zag — distinct from
# Duolingo's hard symmetrical zig-zag, gentle enough not to push nodes
# off-canvas on narrow viewports.
PATH_OFFSET_PATTERN: tuple[int, ...] = (0, 28, 18, -22, -10)


@dataclass(frozen=True)
class PathNode:
    """One node on the dashboard path."""

    lesson_id: int
    title: str
    lesson_type: str
    icon: str
    state: str          # 'done' | 'current' | 'locked' | 'open'
    url: str            # URL to open this lesson
    offset_px: int      # cosmetic horizontal offset
    position: int       # 1-based index within the module
    score: Optional[int] = None  # last completion score, if any

    def to_dict(self) -> dict[str, Any]:
        return {
            'lesson_id': self.lesson_id,
            'title': self.title,
            'lesson_type': self.lesson_type,
            'icon': self.icon,
            'state': self.state,
            'url': self.url,
            'offset_px': self.offset_px,
            'position': self.position,
            'score': self.score,
        }


@dataclass(frozen=True)
class PathModule:
    """Module-level header data accompanying a path."""

    id: int
    number: int
    title: str
    level_code: str
    total_lessons: int
    completed_lessons: int
    catalog_url: str  # legacy module page (the "Справочник" CTA)

    @property
    def percent(self) -> int:
        if self.total_lessons <= 0:
            return 0
        return round(self.completed_lessons / self.total_lessons * 100)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'number': self.number,
            'title': self.title,
            'level_code': self.level_code,
            'total_lessons': self.total_lessons,
            'completed_lessons': self.completed_lessons,
            'percent': self.percent,
            'catalog_url': self.catalog_url,
        }


def _last_completed_module(user_id: int, db: Any) -> Optional[Module]:
    """Return the module owning the user's most recently completed lesson."""
    row = (
        db.session.query(Lessons)
        .join(LessonProgress, LessonProgress.lesson_id == Lessons.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        )
        .order_by(LessonProgress.completed_at.desc().nullslast())
        .first()
    )
    if row is None:
        return None
    return db.session.get(Module, row.module_id)


def _first_visible_module(user_id: int, db: Any) -> Optional[Module]:
    """Return the lowest-order module the user is allowed to see.

    Fallback when the user has zero progress AND no next lesson (e.g.
    every module is gated behind prerequisites or the curriculum is
    empty). Returns the first module by (level.order, number).
    """
    from app.daily_plan.linear.progression import _user_min_level_order

    min_order = _user_min_level_order(user_id, db)
    return (
        db.session.query(Module)
        .join(CEFRLevel, CEFRLevel.id == Module.level_id)
        .filter(CEFRLevel.order >= min_order)
        .order_by(CEFRLevel.order.asc(), Module.number.asc())
        .first()
    )


def get_current_module_for_user(user_id: int, db: Any) -> Optional[Module]:
    """Return the module that should be displayed on the path dashboard.

    Resolution order:
      1. Module owning ``find_next_lesson_linear`` (the active next lesson)
      2. Most-recently-completed module (curriculum-finished users)
      3. First module visible to the user (fresh user, never started)
      4. ``None`` if the curriculum is empty / fully gated
    """
    next_lesson = find_next_lesson_linear(user_id, db)
    if next_lesson is not None:
        module = db.session.get(Module, next_lesson.module_id)
        if module is not None:
            return module

    completed = _last_completed_module(user_id, db)
    if completed is not None:
        return completed

    return _first_visible_module(user_id, db)


def _lesson_icon(lesson_type: Optional[str]) -> str:
    return LESSON_TYPE_ICONS.get((lesson_type or '').lower(), DEFAULT_LESSON_ICON)


def _resolve_lesson_url(lesson: Lessons) -> str:
    """Return the canonical /learn/<id>/ URL for a lesson.

    Plan-context query params (``from``, ``slot``) are NOT appended here:
    the dashboard path is the catalog flow, not the daily-plan flow. The
    side rail still routes through ``build_slot_url`` for plan-aware
    slots.
    """
    return f'/learn/{lesson.id}/'


def _resolve_catalog_url(module: Module) -> str:
    """Return the legacy module-overview URL used by the «Справочник» CTA."""
    level_code = (module.level.code if module.level else 'a0').lower()
    return f'/learn/{level_code}/{module.number}/'


def build_path_nodes(module: Module, user_id: int, db: Any) -> list[PathNode]:
    """Return one ``PathNode`` per lesson of ``module``, in display order.

    Display rules:
      - ``done``: lesson has a LessonProgress(status='completed')
      - ``current``: first non-done lesson (only ONE current per path)
      - ``locked``: every lesson AFTER the current one
      - ``open``: lessons BEFORE the current one with no progress yet
        (rare in the linear spine, but possible if a user skipped via
        admin import). Treated as openable, same as done for navigation.

    A path with zero non-done lessons (module fully completed) has no
    ``current`` — every node is ``done`` and the templates promote the
    last node as the "review" anchor.
    """
    lessons = (
        db.session.query(Lessons)
        .filter(Lessons.module_id == module.id)
        .order_by(Lessons.number.asc(), Lessons.id.asc())
        .all()
    )
    if not lessons:
        return []

    progress_rows = (
        db.session.query(LessonProgress)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.lesson_id.in_([l.id for l in lessons]),
        )
        .all()
    )
    completed_ids = {p.lesson_id for p in progress_rows if p.status == 'completed'}
    score_by_lesson = {p.lesson_id: p.score for p in progress_rows if p.score is not None}

    current_assigned = False
    nodes: list[PathNode] = []
    for index, lesson in enumerate(lessons):
        offset = PATH_OFFSET_PATTERN[index % len(PATH_OFFSET_PATTERN)]
        if lesson.id in completed_ids:
            state = 'done'
        elif not current_assigned:
            state = 'current'
            current_assigned = True
        else:
            state = 'locked'

        nodes.append(
            PathNode(
                lesson_id=lesson.id,
                title=lesson.title or '',
                lesson_type=lesson.type or '',
                icon=_lesson_icon(lesson.type),
                state=state,
                url=_resolve_lesson_url(lesson),
                offset_px=offset,
                position=index + 1,
                score=int(score_by_lesson.get(lesson.id)) if score_by_lesson.get(lesson.id) is not None else None,
            )
        )
    return nodes


def build_path_module(module: Module, nodes: list[PathNode]) -> PathModule:
    """Compose the ``PathModule`` header from a module + its computed nodes."""
    return PathModule(
        id=module.id,
        number=module.number,
        title=module.title or '',
        level_code=(module.level.code if module.level else 'A0'),
        total_lessons=len(nodes),
        completed_lessons=sum(1 for n in nodes if n.state == 'done'),
        catalog_url=_resolve_catalog_url(module),
    )
