"""Dashboard path-progression assembly.

The path-style ``/dashboard`` is a vertical ribbon of three logical
segments rendered as a single visual flow:

1. **Today** — one node per slot of the linear daily plan
   (curriculum / SRS / book / listening / speaking / writing / error_review).
   Nodes carry plan-slot URLs (already include ``?from=linear_plan&slot=<kind>``).

2. **Challenge** — an optional bonus node representing today's daily
   challenge. Rendered with gold-purple visual and a ``×2 XP`` badge.

3. **Preview** — up to N upcoming curriculum-spine lessons after the
   user's current position. Visually muted, opens in catalog-flow (no
   plan query params), grouped by module so the label reads
   ``Дальше в курсе · A2/M1 — <module title>``.

Pure data assembly: no Flask request access, no template logic. The
templates render whatever segments are non-empty and skip the rest.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
from app.daily_plan.linear.progression import find_next_lesson_linear

logger = logging.getLogger(__name__)


# ─── Icon maps ───────────────────────────────────────────────────────

# Generic, neutral emoji set — distinct from Duolingo's bespoke
# illustrations.  Templates may swap for SVG later; the icon mapping
# stays here so all path code agrees.
SLOT_KIND_ICONS: dict[str, str] = {
    'curriculum': '📚',
    'srs': '🔁',
    # 'reading' is the slot.kind emitted by reading_slot.py; 'book' is the
    # URL-param kind via LinearSlotKind.BOOK.  Both map to the same icon
    # so the path doesn't care which convention upstream used.
    'reading': '📖',
    'book': '📖',
    'listening': '🎧',
    'speaking': '🎤',
    'writing': '✍️',
    'error_review': '🛠',
}
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
DEFAULT_ICON = '🎓'
CHALLENGE_ICON = '✨'

# Cosmetic horizontal offsets so the column doesn't read like a straight
# list. Deliberately gentler than Duolingo's full zig-zag.
PATH_OFFSET_PATTERN: tuple[int, ...] = (0, 28, 18, -22, -10)

PREVIEW_DEFAULT_LIMIT = 5


# ─── Dataclasses ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class PathNode:
    """One renderable bubble on the path.

    ``segment`` plus ``state`` together drive the visuals:
      - segment='today' / state in {done, current, locked}
      - segment='challenge' / state='bonus'
      - segment='preview' / state='preview'
    """

    title: str
    icon: str
    state: str
    url: str
    segment: str
    offset_px: int
    slot_kind: Optional[str] = None      # for today-segment nodes
    lesson_id: Optional[int] = None      # for preview / challenge nodes
    score: Optional[int] = None
    badge: Optional[str] = None          # e.g. '×2 XP' for challenge
    eta_minutes: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'title': self.title,
            'icon': self.icon,
            'state': self.state,
            'url': self.url,
            'segment': self.segment,
            'offset_px': self.offset_px,
            'slot_kind': self.slot_kind,
            'lesson_id': self.lesson_id,
            'score': self.score,
            'badge': self.badge,
            'eta_minutes': self.eta_minutes,
        }


@dataclass(frozen=True)
class PathSegment:
    """A labelled group of contiguous nodes.

    ``kind`` is the canonical segment id used by templates; ``label`` is
    the human-readable header shown above the segment ('СЕГОДНЯ — …' or
    'ДАЛЬШЕ В КУРСЕ · A2/M1 …').
    """

    kind: str
    label: str
    nodes: list[PathNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'kind': self.kind,
            'label': self.label,
            'nodes': [n.to_dict() for n in self.nodes],
        }


@dataclass(frozen=True)
class DashboardPath:
    """Top-level assembly returned to the template."""

    segments: list[PathSegment] = field(default_factory=list)
    preview_module_label: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return not any(seg.nodes for seg in self.segments)

    def to_dict(self) -> dict[str, Any]:
        return {
            'segments': [s.to_dict() for s in self.segments],
            'preview_module_label': self.preview_module_label,
            'is_empty': self.is_empty,
        }


# ─── Today segment ───────────────────────────────────────────────────


def _slot_to_node(
    slot: dict[str, Any], state: str, offset_idx: int,
) -> PathNode:
    kind = slot.get('kind') or ''
    return PathNode(
        title=slot.get('title') or '',
        icon=SLOT_KIND_ICONS.get(kind, DEFAULT_ICON),
        state=state,
        url=slot.get('url') or '',
        segment='today',
        offset_px=PATH_OFFSET_PATTERN[offset_idx % len(PATH_OFFSET_PATTERN)],
        slot_kind=kind,
        eta_minutes=slot.get('eta_minutes'),
    )


def _build_today_segment(
    linear_plan: dict[str, Any],
    plan_completion: dict[str, Any],
) -> PathSegment:
    """Map plan slots → today-segment nodes.

    State priority:
      1. ``done``    — slot.completed OR plan_completion[kind] True (baseline).
      2. ``current`` — first non-done slot.
      3. ``locked``  — every subsequent slot.

    Extension slots (beyond ``baseline_count``) trust slot.completed only;
    plan_completion is keyed by kind and would falsely mark an extension
    SRS done the moment the baseline SRS was completed.
    """
    slots = (linear_plan or {}).get('slots') or (linear_plan or {}).get('baseline_slots') or []
    if not slots:
        return PathSegment(kind='today', label='', nodes=[])

    chain_meta = (linear_plan or {}).get('chain_meta') or {}
    baseline_count = chain_meta.get('baseline_count', len(slots))
    completion = plan_completion or {}

    nodes: list[PathNode] = []
    current_assigned = False
    for idx, slot in enumerate(slots):
        if slot.get('skipped'):
            # Skipped slots simply don't appear in the path — they
            # already have their own «Пропустить» action in the rail.
            continue
        kind = slot.get('kind') or ''
        is_baseline = idx < baseline_count
        completed = bool(slot.get('completed')) or (
            is_baseline and bool(completion.get(kind))
        )
        if completed:
            state = 'done'
        elif not current_assigned:
            state = 'current'
            current_assigned = True
        else:
            state = 'locked'
        nodes.append(_slot_to_node(slot, state, idx))

    return PathSegment(kind='today', label='СЕГОДНЯ', nodes=nodes)


# ─── Challenge segment ──────────────────────────────────────────────


def _build_challenge_segment(
    challenge: Optional[dict[str, Any]],
    offset_idx: int,
) -> PathSegment:
    if not challenge:
        return PathSegment(kind='challenge', label='', nodes=[])
    if challenge.get('is_completed'):
        # Don't render a bonus node for an already-claimed challenge —
        # ``×2 XP`` next to a checkmark is just noise.
        return PathSegment(kind='challenge', label='', nodes=[])
    lesson_id = challenge.get('lesson_id')
    if not lesson_id:
        return PathSegment(kind='challenge', label='', nodes=[])
    bonus_xp = challenge.get('bonus_xp') or 0
    node = PathNode(
        title=challenge.get('title') or 'Челлендж дня',
        icon=CHALLENGE_ICON,
        state='bonus',
        url=f'/learn/{lesson_id}/',
        segment='challenge',
        offset_px=PATH_OFFSET_PATTERN[offset_idx % len(PATH_OFFSET_PATTERN)],
        lesson_id=lesson_id,
        badge=f'×{2 if bonus_xp else 1} XP',
    )
    return PathSegment(kind='challenge', label='БОНУС', nodes=[node])


# ─── Preview segment ────────────────────────────────────────────────


def _user_min_order(user_id: int, db: Any) -> int:
    from app.daily_plan.linear.progression import _user_min_level_order
    return _user_min_level_order(user_id, db)


def get_curriculum_preview(
    user_id: int, db: Any, limit: int = PREVIEW_DEFAULT_LIMIT,
) -> list[Lessons]:
    """Return up to ``limit`` upcoming lessons on the curriculum spine.

    Walking order: same as ``find_next_lesson_linear`` (level.order,
    module.number, lesson.number), filtered against the user's
    onboarding level and skipping completed lessons.

    Used for the preview-segment tail under today's plan so the user
    has a sense of what's coming next. NEVER appends plan-context query
    params to URLs — preview opens in catalog flow.
    """
    min_order = _user_min_order(user_id, db)
    completed_subq = (
        db.session.query(LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        )
        .subquery()
    )
    q = (
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
        .limit(max(limit * 2, limit))  # over-fetch to allow current-slot dedup
    )
    return list(q.all())


def _build_preview_segment(
    user_id: int,
    db: Any,
    today_lesson_ids: set[int],
    limit: int,
    today_node_count: int,
) -> tuple[PathSegment, Optional[str]]:
    """Build the preview segment + a module label for the section header.

    ``today_lesson_ids`` lets us skip lessons that already appear as the
    current today-curriculum slot — otherwise the preview's first node
    is a duplicate of the today's primary CTA.
    """
    upcoming = get_curriculum_preview(user_id, db, limit=limit + len(today_lesson_ids) + 1)
    if not upcoming:
        return PathSegment(kind='preview', label='', nodes=[]), None

    # Drop anything already represented in today's segment.
    upcoming = [l for l in upcoming if l.id not in today_lesson_ids][:limit]
    if not upcoming:
        return PathSegment(kind='preview', label='', nodes=[]), None

    # Module label: first preview lesson's parent module.
    first_module = db.session.get(Module, upcoming[0].module_id)
    label_module = (
        first_module.title if first_module and first_module.title else f'Модуль {upcoming[0].module_id}'
    )
    level_code = (first_module.level.code if first_module and first_module.level else 'A0')
    preview_module_label = f'ДАЛЬШЕ В КУРСЕ · {level_code}/M{first_module.number if first_module else 0} — {label_module}'

    nodes: list[PathNode] = []
    for i, lesson in enumerate(upcoming):
        nodes.append(PathNode(
            title=lesson.title or '',
            icon=LESSON_TYPE_ICONS.get((lesson.type or '').lower(), DEFAULT_ICON),
            state='preview',
            url=f'/learn/{lesson.id}/',
            segment='preview',
            offset_px=PATH_OFFSET_PATTERN[(today_node_count + i + 2) % len(PATH_OFFSET_PATTERN)],
            lesson_id=lesson.id,
        ))
    return PathSegment(kind='preview', label=preview_module_label, nodes=nodes), preview_module_label


# ─── Public entry point ─────────────────────────────────────────────


def build_dashboard_path(
    user_id: int,
    db: Any,
    linear_plan: Optional[dict[str, Any]] = None,
    plan_completion: Optional[dict[str, Any]] = None,
    challenge: Optional[dict[str, Any]] = None,
    preview_limit: int = PREVIEW_DEFAULT_LIMIT,
) -> DashboardPath:
    """Return the assembled three-segment path for the dashboard.

    Callers from the dashboard route should pass the already-built
    ``linear_plan``, ``plan_completion``, and ``challenge`` payloads to
    avoid duplicate DB work. Tests can pass them directly without
    hitting the plan assembler.
    """
    today = _build_today_segment(linear_plan or {}, plan_completion or {})
    challenge_seg = _build_challenge_segment(challenge, offset_idx=len(today.nodes))

    # Collect lesson IDs already represented in today's curriculum slot
    # so the preview doesn't repeat them right after.
    today_lesson_ids: set[int] = set()
    for slot in (linear_plan or {}).get('slots') or []:
        if slot.get('kind') == 'curriculum':
            data = slot.get('data') or {}
            lid = data.get('lesson_id')
            if isinstance(lid, int):
                today_lesson_ids.add(lid)

    preview, preview_label = _build_preview_segment(
        user_id, db, today_lesson_ids,
        limit=preview_limit,
        today_node_count=len(today.nodes) + len(challenge_seg.nodes),
    )

    segments = [s for s in (today, challenge_seg, preview) if s.nodes]
    return DashboardPath(segments=segments, preview_module_label=preview_label)
