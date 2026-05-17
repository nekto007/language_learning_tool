"""Linear daily plan assembly.

Assembles the linear-plan payload returned to dashboards/API when
``User.use_linear_plan`` is enabled: header position, level progress,
baseline slots (curriculum / SRS / reading / optional error review),
the continuation preview, and a ``day_secured`` flag derived from slot
completion. Each slot is computed at request time from authoritative
DB state; ``/api/daily-status`` then recomputes ``day_secured`` from
activity summaries (mirroring the mission flow) so that slot state
stays in sync with what the user has actually done today.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.auth.models import User
from app.curriculum.models import Lessons
from app.daily_plan.linear.progression import (
    LevelProgress,
    find_next_lesson_linear,
    get_spine_upcoming,
    get_user_level_progress,
)
from app.utils.db import db

VALID_FOCUSES = {'grammar', 'vocabulary', 'reading', 'speaking', 'all'}

SLOT_ESTIMATED_MINUTES: dict[str, int] = {
    'curriculum': 15,
    'srs': 10,
    'reading': 15,
    'listening': 10,
    'speaking': 8,
    'writing': 8,
    'error_review': 12,
}


def get_plan_intensity(minutes: int) -> str:
    """Return intensity label based on total estimated minutes.

    < 15 min → 'light'; 15-30 → 'normal'; > 30 → 'intensive'.
    """
    if minutes < 15:
        return 'light'
    if minutes <= 30:
        return 'normal'
    return 'intensive'


def _get_user_focus(user_id: int, db_session: Any) -> Optional[str]:
    """Return the first onboarding-focus tag for the user, or None.

    ``User.onboarding_focus`` is stored as a comma-separated string of
    tags (one of ``grammar``/``vocabulary``/``reading``/``all``). Plan
    routing only uses the primary tag, so we split and return the first
    valid value. Unknown tags fall back to None to keep the plan in its
    standard shape.
    """
    user = db_session.session.get(User, user_id)
    if user is None:
        return None
    raw = getattr(user, 'onboarding_focus', None)
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    if not parts:
        return None
    primary = parts[0]
    if primary not in VALID_FOCUSES or primary == 'all':
        return None
    return primary

logger = logging.getLogger(__name__)


def build_tomorrow_preview(user_id: int, db_session: Any) -> dict[str, Any]:
    """Build a brief preview of tomorrow's expected slots.

    Returns ``{estimated_minutes, slot_types}`` for display in the day-secured
    banner. Tomorrow's baseline mirrors today's structure (same slot kinds),
    which is a valid approximation since the chain is deterministic from DB
    state and slot types are stable day-to-day.
    """
    try:
        from app.daily_plan.linear.chain import _build_baseline, _get_plan_difficulty
        difficulty = _get_plan_difficulty(user_id, db_session)
        baseline = _build_baseline(user_id, db_session, difficulty=difficulty)
        slot_types = [s['kind'] for s in baseline]
        estimated_minutes = sum(SLOT_ESTIMATED_MINUTES.get(kind, 0) for kind in slot_types)
        return {
            'estimated_minutes': estimated_minutes,
            'slot_types': slot_types,
        }
    except Exception:
        logger.warning("build_tomorrow_preview failed user=%s", user_id, exc_info=True)
        default_types = ['curriculum', 'srs', 'reading']
        return {
            'estimated_minutes': sum(SLOT_ESTIMATED_MINUTES.get(k, 0) for k in default_types),
            'slot_types': default_types,
        }


def _get_skipped_slot_kinds(
    user_id: int,
    plan_date: Any,
    db_session: Any,
) -> set[str]:
    """Return slot kinds the user explicitly skipped today."""
    from app.daily_plan.models import DailyPlanEvent
    events = db_session.session.query(DailyPlanEvent).filter_by(
        user_id=user_id,
        event_type='slot_skipped',
        plan_date=plan_date,
    ).all()
    return {e.step_kind for e in events if e.step_kind}


def _apply_time_of_day_order(
    all_slots: list[dict[str, Any]],
    baseline_count: int,
    user_local_hour: int,
    difficulty: str,
) -> tuple[list[dict[str, Any]], str]:
    """Reorder baseline slots by time-of-day for 'normal' difficulty only.

    Evening (>=20): SRS first (quickest habit), then curriculum.
    Morning (<=9): curriculum first (fresh brain) — already default.
    Otherwise: unchanged.
    Light/intensive difficulty: always use fixed order.
    Returns (slots_list, slot_order_reason).
    """
    if difficulty != 'normal' or baseline_count <= 1:
        return all_slots, 'default'

    baseline = all_slots[:baseline_count]
    rest = all_slots[baseline_count:]

    curriculum_slots = [s for s in baseline if s.get('kind') == 'curriculum']
    srs_slots = [s for s in baseline if s.get('kind') == 'srs']
    other_slots = [s for s in baseline if s.get('kind') not in ('curriculum', 'srs')]

    if user_local_hour >= 20:
        return srs_slots + curriculum_slots + other_slots + rest, 'evening'
    if user_local_hour <= 9:
        return curriculum_slots + srs_slots + other_slots + rest, 'morning'
    return all_slots, 'default'


def compute_linear_day_secured(baseline_slots: list[dict[str, Any]]) -> bool:
    """Return True when every baseline slot is flagged completed.

    All slots in ``baseline_slots`` are required by construction — the
    error-review slot is appended only when ``should_show_error_review``
    fires, so its presence means the user must complete it to secure the
    day. When ``baseline_slots`` is empty (defensive: the assembler
    always returns at least curriculum / SRS / reading) the day is not
    secured.
    """
    if not baseline_slots:
        return False
    return all(bool(slot.get('completed', False)) for slot in baseline_slots)


def _level_progress_to_dict(progress: LevelProgress) -> dict[str, Any]:
    return {
        'level': progress.level,
        'percent': progress.percent,
        'lessons_remaining_in_level': progress.lessons_remaining_in_level,
    }


def _position_from_lesson(lesson: Any) -> Optional[dict[str, Any]]:
    if lesson is None:
        return None
    module = getattr(lesson, 'module', None)
    module_number = getattr(module, 'number', None)
    level = getattr(module, 'level', None) if module is not None else None
    level_code = getattr(level, 'code', None) if level is not None else None
    return {
        'lesson_id': lesson.id,
        'lesson_type': lesson.type,
        'lesson_number': lesson.number,
        'module_id': getattr(lesson, 'module_id', None),
        'module_number': module_number,
        'level_code': level_code,
    }


def _lesson_from_slot_data(slot_dict: dict[str, Any], db_session: Any) -> Optional[Lessons]:
    """Return the lesson referenced by a slot payload, if it still exists."""
    data = slot_dict.get('data') or {}
    lesson_id = data.get('lesson_id')
    if not lesson_id:
        return None
    try:
        return db_session.session.get(Lessons, int(lesson_id))
    except (TypeError, ValueError):
        return None


def get_linear_plan(
    user_id: int,
    db_session: Any = None,
) -> dict[str, Any]:
    """Return the linear daily plan payload.

    The linear plan is timezone-agnostic: slot builders read authoritative
    DB state (LessonProgress, UserChapterProgress, QuizErrorLog) and the
    API layer handles the user's local day when it recomputes
    ``day_secured``. No ``tz`` is needed here.
    """
    session_provider = db_session if db_session is not None else db

    logger.info("linear_plan_assemble user=%s start", user_id)

    next_lesson = find_next_lesson_linear(user_id, session_provider)
    level_progress = get_user_level_progress(user_id, session_provider, next_lesson=next_lesson)
    # The continuation preview must not duplicate what the inline chain
    # already shows: when day_secured is true the chain has a curriculum
    # extension pointing at next_lesson, and even before that the baseline
    # curriculum slot already represents next_lesson. Skip next_lesson and
    # fetch the lessons that come after it on the spine. Bot/dashboard
    # callers that need the next spine lesson directly read ``position``.
    upcoming = []
    if next_lesson is not None:
        upcoming = list(
            get_spine_upcoming(user_id, next_lesson, session_provider, limit=3)
        )

    focus = _get_user_focus(user_id, session_provider)

    logger.info(
        "linear_plan_assemble user=%s focus=%s level=%s level_pct=%d remaining=%d",
        user_id, focus or 'none',
        level_progress.level, level_progress.percent,
        level_progress.lessons_remaining_in_level,
    )

    from app.daily_plan.linear.chain import _get_plan_difficulty, build_chain
    from app.utils.time_utils import get_user_local_date, get_user_local_hour

    chain_result = build_chain(user_id, session_provider)
    all_slots = chain_result['slots']
    baseline_count = chain_result['baseline_count']

    difficulty = _get_plan_difficulty(user_id, session_provider)
    user_local_hour = get_user_local_hour(user_id, session_provider)
    all_slots, slot_order_reason = _apply_time_of_day_order(
        all_slots, baseline_count, user_local_hour, difficulty
    )

    baseline_slots = all_slots[:baseline_count]

    plan_date = get_user_local_date(user_id, session_provider)
    skipped_kinds = _get_skipped_slot_kinds(user_id, plan_date, session_provider)
    if skipped_kinds:
        for slot in all_slots:
            if slot.get('kind') in skipped_kinds and not slot.get('completed', False):
                slot['skipped'] = True

    day_secured = compute_linear_day_secured(baseline_slots)

    slot_summary = " ".join(
        f"{s.get('kind')}={'done' if s.get('completed') else 'pending'}"
        for s in baseline_slots
    )
    logger.info(
        "linear_plan_assemble user=%s done slots=%d day_secured=%s [%s]",
        user_id, len(baseline_slots), day_secured, slot_summary,
    )

    from app.srs.counting import get_new_card_budget

    remaining_new, _remaining_reviews = get_new_card_budget(user_id, session_provider)
    srs_budget_exhausted = remaining_new <= 0

    total_estimated_minutes = sum(
        SLOT_ESTIMATED_MINUTES.get(slot.get('kind', ''), 0)
        for slot in all_slots
        if not slot.get('completed', False)
    )

    tomorrow_preview = build_tomorrow_preview(user_id, session_provider) if day_secured else None

    return {
        'mode': 'linear',
        'position': _position_from_lesson(next_lesson),
        'progress': _level_progress_to_dict(level_progress),
        'baseline_slots': baseline_slots,
        'slots': all_slots,
        'chain_meta': {
            'baseline_count': baseline_count,
            'has_more_available': chain_result['has_more_available'],
            'exhausted_sources': chain_result['exhausted_sources'],
        },
        'continuation': {
            'available': day_secured,
            'next_lessons': [_position_from_lesson(lesson) for lesson in upcoming],
            'srs_budget_exhausted': srs_budget_exhausted,
        },
        'day_secured': day_secured,
        'total_estimated_minutes': total_estimated_minutes,
        'plan_intensity': get_plan_intensity(total_estimated_minutes),
        'tomorrow_preview': tomorrow_preview,
        'slot_order_reason': slot_order_reason,
    }
