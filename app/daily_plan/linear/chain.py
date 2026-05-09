"""Linear daily plan slot chain.

The linear plan starts with a fixed minimum of baseline slots
(curriculum / SRS / reading, plus optional error review) — that minimum
defines ``day_secured``. Once those baseline slots are all completed,
the chain extends with additional pending tasks pulled in priority
order from the same sources (curriculum spine, SRS, reading,
error review). Sources whose state has nothing more to offer today
are skipped, and the chain stops growing as soon as the most recent
slot is incomplete (the user must finish the current task before the
next one is generated).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.daily_plan.linear.context import LinearSlotKind, build_slot_url
from app.daily_plan.linear.progression import find_next_lesson_linear
from app.daily_plan.linear.slots import LinearSlot
from app.daily_plan.linear.slots.curriculum_slot import (
    _CARD_LESSON_TYPES,
    _eta_minutes,
    build_curriculum_slot,
)
from app.daily_plan.linear.slots.error_review_slot import build_error_review_slot
from app.daily_plan.linear.slots.reading_slot import (
    build_reading_slot,
    get_user_reading_preference,
)
from app.daily_plan.linear.slots.srs_slot import (
    build_srs_slot,
    count_linear_plan_srs_due_cards,
    get_srs_budget_remaining,
)

logger = logging.getLogger(__name__)

EXTENSION_PRIORITY: tuple[str, ...] = ('curriculum', 'srs', 'reading', 'error_review')

DEFAULT_MAX_EXTRA = 10


def _curriculum_lesson_ids_in_chain(chain: list[dict[str, Any]]) -> set[int]:
    """Return lesson_ids of every curriculum slot already present in chain."""
    ids: set[int] = set()
    for slot in chain:
        if slot.get('kind') != 'curriculum':
            continue
        lesson_id = (slot.get('data') or {}).get('lesson_id')
        if lesson_id:
            try:
                ids.add(int(lesson_id))
            except (TypeError, ValueError):
                continue
    return ids


def _has_pending_kind(chain: list[dict[str, Any]], kind: str) -> bool:
    for slot in chain:
        if slot.get('kind') == kind and not slot.get('completed', False):
            return True
    return False


def _build_curriculum_extension(
    user_id: int, db: Any, chain: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """Build a fresh pending curriculum slot for the next spine lesson.

    Skips lessons already represented in the chain (so a completed
    curriculum extension does not get re-emitted as pending).
    """
    if _has_pending_kind(chain, 'curriculum'):
        return None
    used_ids = _curriculum_lesson_ids_in_chain(chain)
    next_lesson = find_next_lesson_linear(user_id, db)
    if next_lesson is None or next_lesson.id in used_ids:
        return None

    module = getattr(next_lesson, 'module', None)
    level = getattr(module, 'level', None) if module is not None else None
    base_url = f'/learn/{next_lesson.id}/'
    if next_lesson.type in _CARD_LESSON_TYPES:
        base_url += '?source=linear_plan_card'

    slot = LinearSlot(
        kind='curriculum',
        title=next_lesson.title,
        lesson_type=next_lesson.type,
        eta_minutes=_eta_minutes(next_lesson.type),
        url=build_slot_url(base_url, LinearSlotKind.CURRICULUM),
        completed=False,
        data={
            'lesson_id': next_lesson.id,
            'lesson_number': next_lesson.number,
            'module_id': getattr(next_lesson, 'module_id', None),
            'module_number': getattr(module, 'number', None),
            'level_code': getattr(level, 'code', None) if level is not None else None,
            'extension': True,
        },
    )
    return slot.to_dict()


def _build_srs_extension(
    user_id: int, db: Any, chain: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """Append an SRS slot only when there are due cards or new-card budget left."""
    if _has_pending_kind(chain, 'srs'):
        return None
    due = count_linear_plan_srs_due_cards(user_id, db)
    budget = get_srs_budget_remaining(user_id, db)
    if due <= 0 and budget <= 0:
        return None
    slot_dict = build_srs_slot(user_id, db, curriculum_lesson=None).to_dict()
    if slot_dict.get('completed'):
        return None
    data = dict(slot_dict.get('data') or {})
    data['extension'] = True
    slot_dict['data'] = data
    return slot_dict


def _build_reading_extension(
    user_id: int, db: Any, chain: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """Append a reading slot only when the user has a chosen book and not read enough today."""
    if _has_pending_kind(chain, 'reading'):
        return None
    if get_user_reading_preference(user_id, db) is None:
        return None
    slot_dict = build_reading_slot(user_id, db).to_dict()
    if slot_dict.get('completed'):
        return None
    data = dict(slot_dict.get('data') or {})
    data['extension'] = True
    slot_dict['data'] = data
    return slot_dict


def _build_error_review_extension(
    user_id: int, db: Any, chain: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    if _has_pending_kind(chain, 'error_review'):
        return None
    slot = build_error_review_slot(user_id, db)
    if slot is None:
        return None
    slot_dict = slot.to_dict()
    if slot_dict.get('completed'):
        return None
    data = dict(slot_dict.get('data') or {})
    data['extension'] = True
    slot_dict['data'] = data
    return slot_dict


_EXTENSION_BUILDERS = {
    'curriculum': _build_curriculum_extension,
    'srs': _build_srs_extension,
    'reading': _build_reading_extension,
    'error_review': _build_error_review_extension,
}


def build_next_slot(
    user_id: int,
    db: Any,
    already_in_chain: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Return the next chain slot, or ``None`` when no source has pending work.

    Sources are tried in ``EXTENSION_PRIORITY`` order. The first source
    that produces a pending (incomplete) slot wins. Sources that are
    exhausted today, or already represented by a pending slot in the
    chain, are skipped.
    """
    for source in EXTENSION_PRIORITY:
        builder = _EXTENSION_BUILDERS[source]
        slot = builder(user_id, db, already_in_chain)
        if slot is not None:
            return slot
    return None


def _build_baseline(user_id: int, db: Any) -> list[dict[str, Any]]:
    """Build the baseline slots (mirrors the legacy linear-plan assembler)."""
    # Imported lazily to avoid a circular import: plan.py imports chain.py
    # in Task 2 once integration lands.
    from app.daily_plan.linear.plan import _get_user_focus, _lesson_from_slot_data

    next_lesson = find_next_lesson_linear(user_id, db)
    focus = _get_user_focus(user_id, db)

    curriculum_dict = build_curriculum_slot(
        user_id, db, next_lesson=next_lesson
    ).to_dict()
    srs_anchor = next_lesson
    if curriculum_dict.get('completed'):
        srs_anchor = _lesson_from_slot_data(curriculum_dict, db) or next_lesson
    srs_dict = build_srs_slot(user_id, db, curriculum_lesson=srs_anchor).to_dict()
    reading_dict = build_reading_slot(user_id, db, focus=focus).to_dict()
    error_review = build_error_review_slot(user_id, db)

    if focus == 'grammar':
        curriculum_dict.setdefault('data', {})['prioritize_grammar'] = True

    if focus == 'reading':
        baseline = [curriculum_dict, reading_dict, srs_dict]
    else:
        baseline = [curriculum_dict, srs_dict, reading_dict]
    if error_review is not None:
        baseline.append(error_review.to_dict())
    return baseline


def build_chain(
    user_id: int,
    db: Any,
    *,
    max_extra: int = DEFAULT_MAX_EXTRA,
) -> dict[str, Any]:
    """Return the full slot chain plus metadata.

    ``slots`` always starts with the baseline (3 or 4 slots); extra
    slots are appended only after the *previous* slot is completed.
    The growth loop stops at the first incomplete slot or when no
    source can supply more work today.

    Returns::

        {
          'slots': list[dict],          # baseline + extras
          'baseline_count': int,        # len(baseline)
          'has_more_available': bool,   # True if a future request could grow
          'exhausted_sources': list[str],
        }
    """
    baseline = _build_baseline(user_id, db)
    chain: list[dict[str, Any]] = list(baseline)
    baseline_count = len(baseline)

    # Stop if any baseline slot is still incomplete — the user must finish
    # the minimum before the chain extends.
    if any(not slot.get('completed', False) for slot in baseline):
        logger.info(
            "chain user=%s baseline_pending=%d/%d extras_skipped=true",
            user_id,
            sum(1 for s in baseline if not s.get('completed')),
            baseline_count,
        )
        return {
            'slots': chain,
            'baseline_count': baseline_count,
            'has_more_available': True,
            'exhausted_sources': [],
        }

    has_more_available = True
    extras_added = 0
    while extras_added < max_extra:
        if not chain[-1].get('completed', False):
            break
        next_slot = build_next_slot(user_id, db, chain)
        if next_slot is None:
            has_more_available = False
            break
        chain.append(next_slot)
        extras_added += 1

    # Report a source as "exhausted" only when it has nothing to offer today.
    # Skip sources whose pending slot is already represented in the chain —
    # those builders return None due to the _has_pending_kind guard, which
    # would mislabel them as exhausted.
    exhausted_sources = []
    for source in EXTENSION_PRIORITY:
        if _has_pending_kind(chain, source):
            continue
        if _EXTENSION_BUILDERS[source](user_id, db, chain) is None:
            exhausted_sources.append(source)

    logger.info(
        "chain user=%s baseline=%d extras=%d total=%d has_more=%s exhausted=%s",
        user_id, baseline_count, extras_added, len(chain),
        has_more_available, ','.join(exhausted_sources) or 'none',
    )
    return {
        'slots': chain,
        'baseline_count': baseline_count,
        'has_more_available': has_more_available,
        'exhausted_sources': exhausted_sources,
    }
