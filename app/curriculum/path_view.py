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


# ─── Icon keys ───────────────────────────────────────────────────────

# Icon keys (resolved to inline SVG by components/_path_icon.html).
# Using string keys instead of emoji lets us swap to a consistent
# stroke-icon set without round-tripping through emoji fonts and gives
# the templates one source of truth.
SLOT_KIND_ICONS: dict[str, str] = {
    'curriculum': 'book-open',
    'srs': 'repeat',
    # 'reading' is the slot.kind emitted by reading_slot.py; 'book' is
    # the URL-param kind via LinearSlotKind.BOOK. Both map to the same
    # icon so the path doesn't care which convention upstream used.
    'reading': 'book',
    'book': 'book',
    'listening': 'headphones',
    'speaking': 'mic',
    'writing': 'pen',
    'error_review': 'wrench',
}
LESSON_TYPE_ICONS: dict[str, str] = {
    'vocabulary': 'book-open',
    'card': 'cards',
    'flashcards': 'cards',
    'anki_cards': 'cards',
    'grammar': 'pen',
    'quiz': 'target',
    'listening_quiz': 'headphones',
    'dialogue_completion_quiz': 'message',
    'ordering_quiz': 'shuffle',
    'translation_quiz': 'globe',
    'reading': 'book',
    'text': 'book',
    'listening_immersion': 'headphones',
    'dictation': 'edit',
    'audio_fill_blank': 'headphones',
    'shadow_reading': 'mic',
    'translation': 'globe',
    'sentence_correction': 'pen',
    'sentence_completion': 'pen',
    'collocation_matching': 'link',
    'writing_prompt': 'pen',
    'pronunciation': 'mic',
    'idiom': 'lightbulb',
    'matching': 'puzzle',
    'final_test': 'flag',
}
DEFAULT_ICON = 'circle'
CHALLENGE_ICON = 'sparkles'
MILESTONE_ICON = 'trophy'

# Localised slot-kind labels used in copy + ARIA labels. Keep all
# user-facing strings in Russian; legacy English fragments like
# "Curriculum complete" get rewritten via _slot_title_localised().
SLOT_KIND_LABELS_RU: dict[str, str] = {
    'curriculum': 'Урок курса',
    'srs': 'Повторение слов',
    'reading': 'Чтение книги',
    'book': 'Чтение книги',
    'listening': 'Аудирование',
    'speaking': 'Говорение',
    'writing': 'Письмо',
    'error_review': 'Разбор ошибок',
}

# Genitive (after-X) forms of slot actions — used to build dynamic
# locked-reason copy that refers to the *preceding* slot in the chain.
# Example: locked SRS slot after a reading slot reads
# «Откроется после чтения» (not «Откроется после повторения», which
# self-references the slot itself).
SLOT_KIND_GENITIVE_RU: dict[str, str] = {
    'curriculum': 'урока',
    'srs': 'повторения',
    'reading': 'чтения',
    'book': 'чтения',
    'listening': 'аудирования',
    'speaking': 'говорения',
    'writing': 'письма',
    'error_review': 'разбора ошибок',
}
LOCKED_REASON_DEFAULT_RU = 'Откроется после предыдущего шага'


def _build_locked_reason(prev_kind: Optional[str]) -> str:
    """Compose 'Откроется после <X>' from the kind of the slot that
    immediately precedes the locked one in the chain."""
    if not prev_kind:
        return LOCKED_REASON_DEFAULT_RU
    action = SLOT_KIND_GENITIVE_RU.get(prev_kind)
    if not action:
        return LOCKED_REASON_DEFAULT_RU
    return f'Откроется после {action}'

# Cosmetic horizontal offsets so the column doesn't read like a straight
# list. Deliberately gentler than Duolingo's full zig-zag.
PATH_OFFSET_PATTERN: tuple[int, ...] = (0, 28, 18, -22, -10)

PREVIEW_DEFAULT_LIMIT = 8


# ─── Dataclasses ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class PathNode:
    """One renderable bubble (or task-card) on the path.

    ``segment`` plus ``state`` together drive the visuals:
      - segment='today' / state in {done, current, locked, milestone}
      - segment='challenge' / state='bonus'
      - segment='preview' / state='preview'
    """

    title: str
    icon: str                 # icon key, resolved to SVG by template
    state: str
    url: str
    segment: str
    offset_px: int
    slot_kind: Optional[str] = None      # for today-segment nodes
    lesson_id: Optional[int] = None      # for preview / challenge nodes
    score: Optional[int] = None
    badge: Optional[str] = None          # e.g. '×2 XP' for challenge
    eta_minutes: Optional[int] = None
    label: Optional[str] = None          # short kind label (e.g. «Повторение слов»)
    locked_reason: Optional[str] = None  # «Откроется после повторения»
    xp_reward: Optional[int] = None      # est. XP for current/preview nodes

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
            'label': self.label,
            'locked_reason': self.locked_reason,
            'xp_reward': self.xp_reward,
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


def _slot_title_localised(slot: dict[str, Any]) -> str:
    """Return a Russian title for the slot, rewriting legacy English fragments.

    The linear plan assembler sometimes returns 'Curriculum complete'
    (English) for finished-curriculum users — we never want that to
    leak into the dashboard. Same defensive treatment for other known
    legacy strings.
    """
    raw = (slot.get('title') or '').strip()
    if not raw:
        return SLOT_KIND_LABELS_RU.get(slot.get('kind') or '', '')
    # Map known English placeholders to Russian + milestone state.
    legacy_map = {
        'Curriculum complete': 'Курс пройден',
        'Curriculum completed': 'Курс пройден',
        'Plan complete': 'План завершён',
    }
    return legacy_map.get(raw, raw)


def _slot_to_node(
    slot: dict[str, Any], state: str, offset_idx: int,
    prev_slot_kind: Optional[str] = None,
    milestone_context: Optional[str] = None,
    allow_milestone: bool = True,
) -> PathNode:
    kind = slot.get('kind') or ''
    title = _slot_title_localised(slot)
    label = SLOT_KIND_LABELS_RU.get(kind)

    # Milestone state: curriculum slot whose title marks «finished» AND
    # the caller has confirmed the user has real completion history.
    # The second check is a belt-and-suspenders defence against legacy
    # callers that mark slots completed when there's no actual progress.
    raw_title = (slot.get('title') or '').strip().lower()
    is_milestone = (
        allow_milestone
        and state == 'done'
        and kind == 'curriculum'
        and raw_title.startswith('curriculum')
    )
    if is_milestone:
        state = 'milestone'
        icon_key = MILESTONE_ICON
        # Milestone label carries WHAT was completed («A2 · Animals» etc.)
        if milestone_context:
            label = milestone_context
    else:
        icon_key = SLOT_KIND_ICONS.get(kind, DEFAULT_ICON)

    locked_reason = _build_locked_reason(prev_slot_kind) if state == 'locked' else None

    return PathNode(
        title=title,
        icon=icon_key,
        state=state,
        url=slot.get('url') or '',
        segment='today',
        offset_px=PATH_OFFSET_PATTERN[offset_idx % len(PATH_OFFSET_PATTERN)],
        slot_kind=kind,
        eta_minutes=slot.get('eta_minutes'),
        label=label,
        locked_reason=locked_reason,
    )


def _get_milestone_context(
    user_id: int, db: Any, linear_plan: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Return «<level> · <last module title>» for a milestone caption.

    Resolution order:
      1. Most-recently-completed module + level via LessonProgress
         («A2 · Animals»). The strong case — works whenever the user
         actually has DB progress.
      2. Level from ``linear_plan['progress']['level']`` (the linear
         plan reports the user's current CEFR level even when there
         are no LessonProgress rows — e.g. legacy data, fresh migration).
         Shows «Уровень A2 пройден».
      3. None — caller falls back to the generic «Урок курса» label.
    """
    try:
        row = (
            db.session.query(Module, CEFRLevel)
            .join(CEFRLevel, CEFRLevel.id == Module.level_id)
            .join(Lessons, Lessons.module_id == Module.id)
            .join(LessonProgress, LessonProgress.lesson_id == Lessons.id)
            .filter(
                LessonProgress.user_id == user_id,
                LessonProgress.status == 'completed',
            )
            .order_by(LessonProgress.completed_at.desc().nullslast())
            .first()
        )
    except Exception:
        logger.warning('milestone_context: query failed', exc_info=True)
        row = None

    if row is not None:
        module, level = row
        level_code = (level.code or '').strip() if level else ''
        module_title = (module.title or '').strip() if module else ''
        if level_code and module_title:
            return f'{level_code} · {module_title}'
        if module_title:
            return module_title

    # Fallback: at least name the level so the celebration has anchor.
    try:
        progress = (linear_plan or {}).get('progress') or {}
        level_code = (progress.get('level') or '').strip()
        if level_code:
            return f'Уровень {level_code} пройден'
    except Exception:
        pass
    return None


def _build_today_segment(
    linear_plan: dict[str, Any],
    plan_completion: dict[str, Any],
    milestone_context: Optional[str] = None,
    allow_milestone: bool = True,
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
    prev_kind: Optional[str] = None
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
        nodes.append(_slot_to_node(
            slot, state, idx,
            prev_slot_kind=prev_kind,
            milestone_context=milestone_context,
            allow_milestone=allow_milestone,
        ))
        prev_kind = kind

    return PathSegment(kind='today', label='Сегодня', nodes=nodes)


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
        label='Бонус',
        xp_reward=bonus_xp,
    )
    return PathSegment(kind='challenge', label='Бонус', nodes=[node])


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


def _get_recent_completed_lessons(
    user_id: int, db: Any, limit: int,
) -> list[Lessons]:
    """Return up to ``limit`` most-recently-completed lessons (newest first).

    Used as the preview-segment fallback when the user has finished the
    curriculum spine — there's nothing to preview, but recently-finished
    lessons make great «можно повторить» candidates.
    """
    rows = (
        db.session.query(Lessons)
        .join(LessonProgress, LessonProgress.lesson_id == Lessons.id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
        )
        .order_by(LessonProgress.completed_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    return list(rows)


def _get_browseable_lessons(
    user_id: int, db: Any, limit: int,
) -> list[Lessons]:
    """Return first ``limit`` lessons from the catalogue.

    Two-pass cascade: first try at the user's CEFR level or above
    (standard catalogue), then drop the filter entirely and pull from
    any level. Catches the «user picked C1, no C1 content yet» case
    where filtering by level would return empty but lower-level lessons
    would still be a perfectly reasonable suggestion to click.

    Final guarantee: if the curriculum has ANY lessons at all, the
    preview tail is populated. Only returns empty when the DB is bare.
    """
    from app.daily_plan.linear.progression import _user_min_level_order
    try:
        min_order = _user_min_level_order(user_id, db)
    except Exception:
        min_order = 0

    def _query(min_level: int):
        try:
            return (
                db.session.query(Lessons)
                .join(Module, Module.id == Lessons.module_id)
                .join(CEFRLevel, CEFRLevel.id == Module.level_id)
                .filter(CEFRLevel.order >= min_level)
                .order_by(
                    CEFRLevel.order.asc(),
                    Module.number.asc(),
                    Lessons.number.asc(),
                    Lessons.id.asc(),
                )
                .limit(limit)
                .all()
            )
        except Exception:
            logger.warning('browseable_lessons: query failed (min=%s)', min_level, exc_info=True)
            return []

    # Pass 1: respect user's level (typical case).
    results = _query(min_order)
    if results:
        return results

    # Pass 2: drop the level filter. C1-user with no C1 content still
    # gets to click something rather than stare at blank space.
    if min_order > 0:
        logger.info(
            "browseable_lessons user=%s: nothing at level order>=%d, falling back to any level",
            user_id, min_order,
        )
        results = _query(0)
    return results


def _build_preview_segment(
    user_id: int,
    db: Any,
    today_lesson_ids: set[int],
    limit: int,
    today_node_count: int,
) -> tuple[PathSegment, Optional[str]]:
    """Build the preview segment + a module label for the section header.

    Strategy (cascading fallbacks — dashboard never goes blank):
      1. Upcoming lessons on the curriculum spine (normal case).
      2. Recently completed lessons («Можно повторить») for users who
         finished the spine.
      3. First lessons from the catalogue («Из каталога курса») for
         fresh / migrated users with no completion history.
    """
    upcoming = get_curriculum_preview(user_id, db, limit=limit + len(today_lesson_ids) + 1)

    # Strategy 1: forward-looking preview on the spine.
    if upcoming:
        upcoming = [l for l in upcoming if l.id not in today_lesson_ids][:limit]
        if upcoming:
            first_module = db.session.get(Module, upcoming[0].module_id)
            label_module = (
                first_module.title if first_module and first_module.title
                else f'Модуль {upcoming[0].module_id}'
            )
            level_code = (first_module.level.code if first_module and first_module.level else 'A1')
            module_label = (
                f'Дальше в курсе · {level_code}/М{first_module.number if first_module else 0} — {label_module}'
            )
            nodes = [_preview_node(lesson, today_node_count, i, kind_label='Урок курса')
                     for i, lesson in enumerate(upcoming)]
            return PathSegment(kind='preview', label=module_label, nodes=nodes), module_label

    # Strategy 2: review-mode preview on recently completed lessons.
    recent = _get_recent_completed_lessons(user_id, db, limit)
    if recent:
        nodes = [_preview_node(lesson, today_node_count, i, kind_label='Можно повторить')
                 for i, lesson in enumerate(recent)]
        return PathSegment(
            kind='preview',
            label='Доступно для повторения',
            nodes=nodes,
        ), None

    # Strategy 3: catalogue browsing.
    browse = _get_browseable_lessons(user_id, db, limit)
    if browse:
        nodes = [_preview_node(lesson, today_node_count, i, kind_label='Из каталога')
                 for i, lesson in enumerate(browse)]
        return PathSegment(
            kind='preview',
            label='Из каталога курса',
            nodes=nodes,
        ), None

    return PathSegment(kind='preview', label='', nodes=[]), None


def _preview_node(
    lesson: Lessons, today_node_count: int, i: int, kind_label: str,
) -> PathNode:
    return PathNode(
        title=lesson.title or '',
        icon=LESSON_TYPE_ICONS.get((lesson.type or '').lower(), DEFAULT_ICON),
        state='preview',
        url=f'/learn/{lesson.id}/',
        segment='preview',
        offset_px=PATH_OFFSET_PATTERN[(today_node_count + i + 2) % len(PATH_OFFSET_PATTERN)],
        lesson_id=lesson.id,
        label=kind_label,
    )


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
    # Authoritative «user has progress» check. Milestone state may ONLY
    # render when there's real LessonProgress history — prevents the
    # «Курс пройден» banner from showing for a fresh user whose plan
    # returned None next-lesson because the catalogue is empty / gated.
    try:
        has_progress = (
            db.session.query(LessonProgress.id)
            .filter(
                LessonProgress.user_id == user_id,
                LessonProgress.status == 'completed',
            )
            .first()
        ) is not None
    except Exception:
        logger.warning('dashboard_path: progress lookup failed', exc_info=True)
        has_progress = False

    milestone_ctx = _get_milestone_context(user_id, db, linear_plan=linear_plan) if has_progress else None
    today = _build_today_segment(
        linear_plan or {}, plan_completion or {},
        milestone_context=milestone_ctx,
        allow_milestone=has_progress,
    )
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
    logger.info(
        "dashboard_path user=%s today=%d challenge=%d preview=%d label=%r milestone_ctx=%r",
        user_id, len(today.nodes), len(challenge_seg.nodes), len(preview.nodes),
        preview.label, milestone_ctx,
    )
    return DashboardPath(segments=segments, preview_module_label=preview_label)
