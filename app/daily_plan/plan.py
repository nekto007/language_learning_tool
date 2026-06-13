"""Unified daily plan orchestrator.

Builds a single plan payload with three sections:

- ``required``  — minimum learning work that closes the day. ``day_secured``
  depends solely on this list.
- ``optional``  — bonus work, up to ``OPTIONAL_MAX`` items, priority-ordered.
- ``setup``     — non-blocking preparation (pick a book, browse catalogue).

Milestone events (day/module/level/book completed) are off-band via the
Notification mechanism; they never appear in the plan payload.

The orchestrator is timezone-agnostic — item builders read authoritative
DB state. ``day_secured`` is recomputed at the API layer from real activity
(``compute_plan_steps`` + ``compute_day_secured_from_activity``).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.items import PlanItem
from app.daily_plan.items.challenge import build_challenge_item
from app.daily_plan.items.curriculum import (
    build_curriculum_completed_item,
    build_curriculum_item,
    build_curriculum_queue,
    get_curriculum_lessons_completed_today,
    has_completed_history,
)
from app.daily_plan.items.error_review import build_error_review_item, determine_section
from app.daily_plan.items.grammar_review import build_grammar_review_item
from app.daily_plan.items.reading import build_reading_item, get_user_reading_preference
from app.daily_plan.items.setup import (
    book_selected_today,
    build_setup_book_item,
    build_setup_level_item,
)
from app.daily_plan.items.skills import (
    build_listening_item,
    build_speaking_item,
    build_writing_item,
)
from app.daily_plan.items.srs import build_srs_item

logger = logging.getLogger(__name__)

OPTIONAL_MAX = 15

# Length of the Duolingo-style continuation queue of upcoming spine lessons
# surfaced in the optional section after the required minimum. Kept below
# ``OPTIONAL_MAX`` so completed-today cards and the other practice sources
# (SRS, reading, …) still fit under the overall cap.
CONTINUATION_QUEUE_LIMIT = 12

# Items that must wait for the curriculum slot to complete — skipping
# curriculum locks them too. Listening is intentionally NOT in this set;
# it walks the spine independently. Optional curriculum is also not blocked
# so users can still complete a bonus lesson after skipping required.
_CURRICULUM_DEPENDENT_KINDS = frozenset({'speaking', 'writing'})


def _get_unified_skipped_kinds(user_id: int, db: Any) -> set[str]:
    """Return the kinds of required items the user skipped today."""
    from app.daily_plan.models import DailyPlanEvent
    from app.utils.time_utils import get_user_local_date

    today = get_user_local_date(user_id, db)
    rows = (
        db.session.query(DailyPlanEvent.step_kind)
        .filter(
            DailyPlanEvent.user_id == user_id,
            DailyPlanEvent.event_type == 'slot_skipped',
            DailyPlanEvent.plan_date == today,
        )
        .all()
    )
    return {row.step_kind for row in rows if row.step_kind}


def _apply_unified_skip_state(
    required_dicts: list[dict[str, Any]],
    skipped_kinds: set[str],
) -> None:
    """Mark skipped items + lock curriculum-dependents after a curriculum skip.

    Mutates ``required_dicts`` in place. Idempotent; safe to call multiple
    times. Items that are already completed are never marked skipped or
    blocked — completion always wins.
    """
    if not skipped_kinds:
        return
    curriculum_skipped = False
    for item in required_dicts:
        if item.get('completed', False):
            continue
        kind = item.get('kind', '')
        if kind in skipped_kinds:
            item['skipped'] = True
            if kind == 'curriculum':
                curriculum_skipped = True
            continue
        if curriculum_skipped and kind in _CURRICULUM_DEPENDENT_KINDS:
            item['blocked'] = True
            item.setdefault('data', {})['locked_reason'] = (
                'Сначала завершите урок курса'
            )


def _annotate_unified_skip_quota(
    required_dicts: list[dict[str, Any]],
    skips_used: int,
) -> None:
    """Expose the daily slot-skip quota on currently actionable items."""
    from app.daily_plan.skips import DAILY_SLOT_SKIP_QUOTA

    skips_remaining = max(DAILY_SLOT_SKIP_QUOTA - skips_used, 0)
    for item in required_dicts:
        if item.get('completed') or item.get('skipped') or item.get('blocked'):
            continue
        data = item.setdefault('data', {})
        data['slot_skip_allowed'] = skips_remaining > 0
        data['slot_skips_remaining'] = skips_remaining

# Priority order for building the non-curriculum optional sources. The
# curriculum continuation queue is built separately (``build_curriculum_queue``)
# and rendered BEFORE these. Items already present in required (matched by
# ``id``) are skipped to avoid duplication.
_OPTIONAL_PRIORITY = (
    'srs',
    'reading',
    'listening',
    'speaking',
    'writing',
    'error_review',
    'grammar_review',
    'challenge',
)


_CARD_LESSON_TYPES = frozenset({'card', 'flashcards'})


def build_required(
    user_id: int,
    db: Any,
    *,
    difficulty: str,
    focus: Optional[str],
    graduated: bool = False,
) -> list[PlanItem]:
    """Assemble the required-section items in caskade order.

    Order: error_review (acute) → SRS (if due > 0 AND not already implied by
    a card-type curriculum lesson) → curriculum → reading → listening.

    SRS de-duplication: when the next curriculum lesson itself is a card /
    flashcards lesson, a plain SRS-cards slot in required would mean the user
    faces two flashcards sessions in a row. To avoid that the required SRS slot
    is swapped for a deck-quiz (a different form factor over the user's custom
    decks) — but ONLY when the user actually has deck words. Without decks the
    deck-quiz would be a dead "no words" placeholder while the real SRS card
    review reappears in optional as ``srs:global`` (a different id the optional
    de-dup can't collapse). So with no decks we keep the ordinary ``srs:global``
    in required, and the optional duplicate then collapses by id.

    Setup items NEVER appear here. Empty list is valid (orchestrator
    reports day not secured and surfaces setup hints).

    Graduated users (all curriculum exhausted, has history) receive an empty
    required list — their work lives entirely in optional (SRS, reading,
    grammar_review with ignore_daily_budget=True).
    """
    if graduated:
        return []

    items: list[PlanItem] = []

    err_section = determine_section(user_id, db)
    if err_section == 'required':
        item = build_error_review_item(user_id, db, section='required')
        if item is not None:
            items.append(item)

    # Resolve curriculum first so we can decide SRS placement based on
    # the upcoming lesson type. The builder is cheap and idempotent.
    cur_item = build_curriculum_item(user_id, db, section='required')
    next_is_card_lesson = (
        cur_item is not None
        and cur_item.lesson_type in _CARD_LESSON_TYPES
        and not cur_item.completed
    )

    # SRS placement rules:
    #   curriculum is NOT card-lesson         → SRS as standard card review
    #   card-lesson pending AND user has decks → SRS as deck quiz (different
    #       form factor over the user's decks, avoids «cards twice today»)
    #   card-lesson pending AND no decks       → standard SRS card review
    #       (a deck quiz would be a dead placeholder, and the real SRS would
    #       otherwise resurface in optional as a non-collapsible duplicate)
    #   card-lesson done                       → SRS as standard card review
    use_deck_quiz = next_is_card_lesson
    if use_deck_quiz:
        from app.daily_plan.linear.slots.srs_slot import _count_user_deck_quiz_words
        use_deck_quiz = _count_user_deck_quiz_words(user_id, db) > 0
    srs_item = build_srs_item(
        user_id, db, section='required',
        as_deck_quiz=use_deck_quiz,
    )
    if srs_item is not None:
        items.append(srs_item)

    if cur_item is not None:
        items.append(cur_item)

    # Reading joins required only when a book is selected AND the selection
    # is NOT from today — otherwise a mid-day book pick would retroactively
    # void an already-secured day. The freshly-picked book lives in optional
    # today and joins required tomorrow.
    pref = get_user_reading_preference(user_id, db)
    if pref is not None and not book_selected_today(user_id, db):
        reading_item = build_reading_item(user_id, db, section='required', focus=focus)
        if reading_item is not None:
            items.append(reading_item)

    if difficulty != 'light':
        listening_item = build_listening_item(user_id, db, section='required')
        if listening_item is not None:
            items.append(listening_item)

    # Difficulty caps for required. Always preserve the curriculum item: it
    # gates curriculum-dependent skills, so truncating it out would let the day
    # be "secured" without the lesson (audit E-027). Cap the OTHER items around
    # it, keeping original priority order.
    cap = 2 if difficulty == 'light' else (4 if difficulty == 'normal' else None)
    if cap is not None:
        if cur_item is not None and cur_item in items:
            others = [it for it in items if it is not cur_item]
            keep = set(id(it) for it in others[:max(0, cap - 1)]) | {id(cur_item)}
            items = [it for it in items if id(it) in keep]
        else:
            items = items[:cap]
    # intensive: no cap

    return items


def build_optional(
    user_id: int,
    db: Any,
    *,
    required_items: list[PlanItem],
    focus: Optional[str],
    graduated: bool = False,
    max_items: int = OPTIONAL_MAX,
) -> tuple[list[PlanItem], bool]:
    """Return (optional_items, has_more) capped at ``max_items``.

    Items already in required (matched by ``id``) are excluded. ``has_more``
    is True when the total candidate count exceeded ``max_items`` (soft hint
    for the dashboard re-fetch affordance; not a per-builder exhaustion signal).

    The required curriculum lesson id is forwarded to the optional curriculum
    builder as ``exclude_lesson_ids`` so the optional slot always returns the
    NEXT lesson on the spine, never the same one already shown in required.
    Without this, when ``done_today=False`` both builders resolve to the same
    lesson, the candidate is silently dropped, and the optional block appears
    empty even though more content exists.
    """
    seen_ids = {it.id for it in required_items}

    def _item_lesson_id(it: PlanItem) -> Optional[int]:
        raw = (it.data or {}).get('lesson_id') if it.data else None
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    # Lessons already surfaced anywhere in the plan (in any kind / section).
    # Used to suppress duplicate cards for the same underlying lesson when a
    # single Lesson row qualifies under more than one builder — e.g. a
    # writing_prompt curriculum lesson would otherwise appear once as a
    # ``curriculum:lesson:NNN`` completed card AND once as a
    # ``writing:lesson:NNN`` skill card.
    seen_lesson_ids: set[int] = set()
    for it in required_items:
        lid = _item_lesson_id(it)
        if lid is not None:
            seen_lesson_ids.add(lid)

    # Extract the required curriculum lesson id so the optional builder skips
    # it and offers the NEXT lesson on the spine instead.
    required_curriculum_lesson_id: Optional[int] = None
    for it in required_items:
        if it.kind == 'curriculum':
            required_curriculum_lesson_id = _item_lesson_id(it)
            break
    exclude_curriculum_ids: Optional[set[int]] = (
        {required_curriculum_lesson_id} if required_curriculum_lesson_id is not None else None
    )

    # Collect completed-curriculum cards first so we can apply seen-id dedup,
    # but defer their insertion into the final list until after we know how
    # many active candidates need slots. Otherwise enough completions in a
    # single day (≥ ``max_items``) would push the next actionable lesson —
    # and other actionable kinds (SRS, reading, …) — past the cap, leaving
    # the user stuck with a wall of done cards on reload.
    completed_curriculum_items: list[PlanItem] = []
    if required_curriculum_lesson_id is not None:
        for completed_lesson in get_curriculum_lessons_completed_today(
            user_id, db, exclude_lesson_ids=exclude_curriculum_ids,
        ):
            completed_item = build_curriculum_completed_item(completed_lesson, section='optional')
            if completed_item.id in seen_ids:
                continue
            completed_curriculum_items.append(completed_item)
            seen_ids.add(completed_item.id)
            cli_lid = _item_lesson_id(completed_item)
            if cli_lid is not None:
                seen_lesson_ids.add(cli_lid)

    # Active candidates, in render order: the curriculum continuation queue
    # first (Duolingo-style «Дальше по курсу» — a long list of upcoming spine
    # lessons), then the other practice sources (SRS, reading, …).
    active_candidates: list[PlanItem] = []

    def _accept(candidate: Optional[PlanItem]) -> bool:
        if candidate is None or candidate.id in seen_ids:
            return False
        candidate_lid = _item_lesson_id(candidate)
        if candidate_lid is not None and candidate_lid in seen_lesson_ids:
            # Same underlying lesson already represented (e.g. surfaced as
            # a completed curriculum card) — drop the duplicate.
            return False
        active_candidates.append(candidate)
        seen_ids.add(candidate.id)
        if candidate_lid is not None:
            seen_lesson_ids.add(candidate_lid)
        return True

    # Curriculum continuation queue: anchor on the required curriculum lesson
    # and walk the spine forward. The anchor (and any lesson already seen) is
    # excluded; the queue is intentionally light (no weak-grammar/adaptive
    # hints). Graduated users have no curriculum anchor — they skip the queue.
    # Over-fetch one extra lesson so we can tell the dashboard there is more
    # spine beyond the displayed cap (``queue_truncated`` → has_more).
    queue_truncated = False
    if required_curriculum_lesson_id is not None:
        from app.curriculum.models import Lessons

        anchor_lesson = db.session.get(Lessons, required_curriculum_lesson_id)
        if anchor_lesson is not None:
            queue_items = build_curriculum_queue(
                user_id, db,
                anchor_lesson=anchor_lesson,
                limit=CONTINUATION_QUEUE_LIMIT + 1,
                exclude_lesson_ids=set(seen_lesson_ids),
                section='optional',
            )
            queue_truncated = len(queue_items) > CONTINUATION_QUEUE_LIMIT
            for queue_item in queue_items[:CONTINUATION_QUEUE_LIMIT]:
                _accept(queue_item)

    # Other practice sources. Each contributes at most one optional item.
    for kind in _OPTIONAL_PRIORITY:
        candidate = _build_optional_candidate(
            user_id, db, kind, focus,
            exclude_curriculum_ids=exclude_curriculum_ids,
            graduated=graduated,
        )
        _accept(candidate)

    # Active candidates take priority over completed cards — drop accumulated
    # completions first if the section would otherwise overflow.
    active_subset = active_candidates[:max_items]
    completed_slots = max(0, max_items - len(active_subset))
    completed_subset = completed_curriculum_items[:completed_slots]
    items = completed_subset + active_subset
    has_more = (
        queue_truncated
        or len(completed_curriculum_items) > len(completed_subset)
        or len(active_candidates) > len(active_subset)
    )
    # ``has_more`` is a soft hint; the dashboard simply re-fetches on demand.
    return items, has_more


def _build_optional_candidate(
    user_id: int,
    db: Any,
    kind: str,
    focus: Optional[str],
    exclude_curriculum_ids: Optional[set[int]] = None,
    graduated: bool = False,
) -> Optional[PlanItem]:
    if kind == 'srs':
        return build_srs_item(
            user_id, db, section='optional',
            ignore_daily_budget=graduated,
        )
    if kind == 'reading':
        return build_reading_item(
            user_id, db, section='optional',
            focus=focus,
        )
    if kind == 'listening':
        return build_listening_item(user_id, db, section='optional')
    if kind == 'speaking':
        return build_speaking_item(user_id, db, section='optional')
    if kind == 'writing':
        return build_writing_item(user_id, db, section='optional')
    if kind == 'error_review':
        section = determine_section(user_id, db)
        if section != 'optional':
            return None
        return build_error_review_item(user_id, db, section='optional')
    if kind == 'grammar_review':
        return build_grammar_review_item(user_id, db, section='optional')
    if kind == 'challenge':
        return build_challenge_item(user_id, db)
    return None


def build_setup(user_id: int, db: Any) -> list[PlanItem]:
    """Build the setup section.

    Emits:
    - ``setup_book`` when no ``UserReadingPreference`` exists.
    - ``setup_level`` when ``find_next_lesson_linear`` is None AND the user
      has no completion history (no eligible content).

    Both are independent — a fresh user with no book and no eligible lesson
    sees both, in this stable order.
    """
    items: list[PlanItem] = []

    pref = get_user_reading_preference(user_id, db)
    if pref is None:
        items.append(build_setup_book_item())

    from app.daily_plan.linear.progression import find_next_lesson_linear

    next_lesson = find_next_lesson_linear(user_id, db)
    if next_lesson is None and not has_completed_history(user_id, db):
        items.append(build_setup_level_item())

    return items


def get_daily_plan(
    user_id: int,
    db_session: Any = None,
) -> dict[str, Any]:
    """Assemble the unified daily plan payload for the user."""
    from app.daily_plan.linear.chain import _get_plan_difficulty
    from app.daily_plan.linear.plan import (
        _get_user_focus,
        _level_progress_to_dict,
        _position_from_lesson,
        get_plan_intensity,
    )
    from app.daily_plan.linear.progression import (
        find_next_lesson_linear,
        get_user_level_progress,
    )
    from app.utils.db import db

    session = db_session if db_session is not None else db

    logger.info("unified_plan_assemble user=%s start", user_id)

    next_lesson = find_next_lesson_linear(user_id, session)
    level_progress = get_user_level_progress(user_id, session, next_lesson=next_lesson)
    focus = _get_user_focus(user_id, session)
    difficulty = _get_plan_difficulty(user_id, session)
    module_progress = _compute_module_progress(user_id, session, next_lesson)

    # Graduated state: no more curriculum lessons but user has completed history.
    # Force optional to include SRS/reading/grammar_review even if daily caps reached.
    graduated = next_lesson is None and has_completed_history(user_id, session)

    required = build_required(user_id, session, difficulty=difficulty, focus=focus, graduated=graduated)
    optional, has_more_optional = build_optional(
        user_id, session, required_items=required, focus=focus, graduated=graduated,
    )
    setup = build_setup(user_id, session)

    # Assembly-time day_secured is always False — required items start
    # uncompleted. API layer recomputes from actual activity.
    day_secured = False

    logger.info(
        "unified_plan_assemble user=%s done req=%d opt=%d setup=%d intensity=%s focus=%s",
        user_id, len(required), len(optional), len(setup), difficulty, focus or 'none',
    )

    if not required:
        logger.warning(
            "unified_plan_assemble user=%s required=[] — all sources exhausted "
            "or blocked. setup=%s",
            user_id, [it.kind for it in setup],
        )

    required_dicts = [it.to_dict() for it in required]
    optional_dicts = [it.to_dict() for it in optional]

    # Pin the required composition to the day's snapshot so the plan the user
    # saw in the morning is the plan they close in the evening. Fresh items
    # whose kind appeared mid-day get demoted to optional instead of growing
    # required. Graduated users have required=[] by design — nothing to pin.
    if not graduated:
        from app.daily_plan.snapshot import reconcile_required_with_snapshot

        required_dicts, demoted = reconcile_required_with_snapshot(
            user_id, required_dicts, session,
        )
        if demoted:
            optional_ids = {it.get('id') for it in optional_dicts}
            for item in demoted:
                if item.get('id') in optional_ids:
                    continue
                item['section'] = 'optional'
                optional_dicts.insert(0, item)
            if len(optional_dicts) > OPTIONAL_MAX:
                optional_dicts = optional_dicts[:OPTIONAL_MAX]
                has_more_optional = True

    # ETA from the reconciled list — carried/completed slots cost 0 minutes.
    total_estimated_minutes = sum(
        int(it.get('eta_minutes') or 0)
        for it in required_dicts
        if not it.get('completed')
    )

    # Apply per-day skip state before serialising so the template sees
    # 'skipped'/'blocked' flags and the skip-quota annotation in one place.
    from app.daily_plan.skips import get_slot_skips_used_today

    skipped_kinds = _get_unified_skipped_kinds(user_id, session)
    if skipped_kinds:
        _apply_unified_skip_state(required_dicts, skipped_kinds)
    from app.utils.time_utils import get_user_local_date
    _annotate_unified_skip_quota(
        required_dicts,
        get_slot_skips_used_today(user_id, get_user_local_date(user_id, session), session),
    )

    return {
        'mode': 'unified',
        'position': _position_from_lesson(next_lesson),
        'progress': _level_progress_to_dict(level_progress),
        'module_progress': module_progress,
        'required': required_dicts,
        'optional': optional_dicts,
        'setup': [it.to_dict() for it in setup],
        'day_secured': day_secured,
        'total_estimated_minutes': total_estimated_minutes,
        'plan_intensity': get_plan_intensity(total_estimated_minutes),
        'has_more_optional': has_more_optional,
        'graduated': graduated,
    }


def _compute_module_progress(user_id: int, db: Any, next_lesson: Any) -> Optional[dict[str, Any]]:
    """Return module title + remaining-lessons count, or None if no module.

    Lightweight DB call — single COUNT for the user's current module so the
    dashboard can show «Артикли и some/any · до конца модуля: 10 уроков»
    instead of the demotivating «осталось 413 уроков на A2».
    """
    if next_lesson is None:
        return None
    module = getattr(next_lesson, 'module', None)
    if module is None:
        return None

    from app.curriculum.models import LessonProgress, Lessons

    total = (
        db.session.query(Lessons.id)
        .filter(Lessons.module_id == module.id)
        .count()
    )
    completed = (
        db.session.query(LessonProgress.id)
        .join(Lessons, Lessons.id == LessonProgress.lesson_id)
        .filter(
            LessonProgress.user_id == user_id,
            LessonProgress.status == 'completed',
            Lessons.module_id == module.id,
        )
        .count()
    )
    remaining = max(total - completed, 0)
    return {
        'module_id': module.id,
        'module_number': module.number,
        'module_title': module.title,
        'lessons_total': total,
        'lessons_completed': completed,
        'lessons_remaining': remaining,
    }
