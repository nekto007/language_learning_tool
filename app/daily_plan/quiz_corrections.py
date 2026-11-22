"""Read-only projection of a durable quiz correction phase into the plan.

The lesson submission service owns ``LessonProgress.data.quiz_correction``.
This module only reads it: an HTTP GET must not mutate an attempt, award XP,
rebuild the frozen daily snapshot, or reset the independent SRS/book work.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Any


@dataclass(frozen=True)
class PendingQuizCorrection:
    progress: Any
    lesson: Any
    state: dict[str, Any]


def correction_state(progress: Any) -> dict[str, Any] | None:
    return correction_state_from_data(getattr(progress, 'data', None))


def correction_state_from_data(data: Any) -> dict[str, Any] | None:
    value = data.get('quiz_correction') if isinstance(data, dict) else None
    if (not isinstance(value, dict) or value.get('version') != 1
            or value.get('status') not in ('pending', 'completed')
            or not isinstance(value.get('attempt_id'), str) or not value['attempt_id']):
        return None
    return value


def is_pending_correction(progress: Any) -> bool:
    state = correction_state(progress)
    return bool(state and state['status'] == 'pending'
                and getattr(progress, 'status', None) == 'in_progress')


def is_completed_correction(progress: Any) -> bool:
    state = correction_state(progress)
    return bool(state and state['status'] == 'completed'
                and getattr(progress, 'status', None) == 'completed')


def pending_quiz_corrections(user_id: int, db: Any) -> list[PendingQuizCorrection]:
    from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module
    from app.daily_plan.linear.progression import _user_min_level_order

    floor = _user_min_level_order(user_id, db)
    rows = (db.session.query(LessonProgress)
            .join(Lessons, Lessons.id == LessonProgress.lesson_id)
            .join(Module, Module.id == Lessons.module_id)
            .join(CEFRLevel, CEFRLevel.id == Module.level_id)
            .filter(LessonProgress.user_id == user_id,
                    LessonProgress.status == 'in_progress', Lessons.type != 'final_test',
                    CEFRLevel.order >= floor)
            .order_by(CEFRLevel.order, Module.number, Lessons.number, Lessons.id).all())
    return [PendingQuizCorrection(progress=row, lesson=row.lesson, state=correction_state(row))
            for row in rows if is_pending_correction(row)]


def _spine_key(lesson: Any) -> tuple[int, int, int, int]:
    module = getattr(lesson, 'module', None)
    level = getattr(module, 'level', None)
    return (int(getattr(level, 'order', 0) or 0), int(getattr(module, 'number', 0) or 0),
            int(getattr(lesson, 'number', 0) or 0), int(getattr(lesson, 'id', 0) or 0))


def pending_correction_blocks_lesson(user_id: int, lesson: Any, db: Any) -> bool:
    """A later dependent lesson stays locked, including an already-open draft."""
    target = _spine_key(lesson)
    return any(_spine_key(pending.lesson) < target
               for pending in pending_quiz_corrections(user_id, db))


def _attempt_day(user_id: int, state: dict[str, Any], db: Any):
    from app.utils.time_utils import get_user_local_date, get_user_timezone_name, study_day_date_for_tz

    raw = state.get('created_at')
    try:
        stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return study_day_date_for_tz(get_user_timezone_name(user_id, db), now_utc=stamp)
    except (AttributeError, TypeError, ValueError):
        # An unreadable legacy date cannot prove that a new pause is owed.
        # Allow the inherited correction now instead of restarting the pause
        # every morning forever.
        return get_user_local_date(user_id, db) - timedelta(days=1)


def _phase_item(pending: PendingQuizCorrection, section: str, *, first_round: bool) -> dict[str, Any]:
    from app.daily_plan.linear.context import LinearSlotKind, build_slot_url

    lesson, state = pending.lesson, pending.state
    module = getattr(lesson, 'module', None)
    level = getattr(module, 'level', None)
    score = state.get('first_score')
    score_label = f' · {score:g}%' if isinstance(score, (int, float)) and not isinstance(score, bool) else ''
    count = len(state.get('pending_ids') or [])
    content = lesson.content
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError:
            content = None
    revision = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    changed = bool(state.get('revision') and state['revision'] != revision)
    return {
        'id': (f'curriculum:lesson:{lesson.id}:first:{state["attempt_id"]}' if first_round
               else f'curriculum:lesson:{lesson.id}'),
        'section': section, 'kind': 'curriculum', 'lesson_type': lesson.type,
        'title': (lesson.title if first_round else f'Повторить обновлённое задание: {lesson.title}'
                  if changed else f'Работа над ошибками: {lesson.title}'),
        'subtitle': (f'Первый круг завершён{score_label}' if first_round else
                     'Материал изменился; начни актуальную попытку' if changed else
                     f'Разбери и исправь ответы: {count}'),
        'eta_minutes': 0 if first_round else max(2, min(count, 10)),
        'completed': first_round, 'completion_signal': 'lesson_completed',
        'url': None if first_round else build_slot_url(
            f'/learn/{lesson.id}/?quiz_phase=correction', LinearSlotKind.CURRICULUM),
        'data': {'lesson_id': lesson.id, 'lesson_number': lesson.number,
                 'module_id': lesson.module_id, 'module_number': getattr(module, 'number', None),
                 'module_title': getattr(module, 'title', None), 'level_code': getattr(level, 'code', None),
                 'quiz_phase': 'first_round' if first_round else 'correction',
                 'quiz_attempt_id': state['attempt_id'], 'pending_count': count,
                 'quiz_material_changed': changed,
                 'slot_skip_allowed': False},
    }


def reconcile_quiz_corrections(
    user_id: int, db: Any, required: list[dict[str, Any]], optional: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Place one correction after today's independent work and before lesson N+1.

    On a later study day, the inherited correction comes before NEW SRS/book
    targets: the pause belongs to the first-round day and must not restart.
    Existing completed independent items keep all their fields and credit.
    """
    from app.curriculum.models import Lessons
    from app.utils.time_utils import get_user_local_date

    pending = pending_quiz_corrections(user_id, db)
    if not pending:
        return required, optional
    # Only the earliest phase can legitimately be active. Legacy/concurrent
    # later states stay behind it and become visible when it is resolved.
    phase = pending[0]
    lesson_id = phase.lesson.id
    groups = [deepcopy(required), deepcopy(optional)]
    located = [(group, index) for group, items in enumerate(groups) for index, item in enumerate(items)
               if item.get('kind') == 'curriculum' and (item.get('data') or {}).get('lesson_id') == lesson_id]
    group_index = located[0][0] if located else 0
    origin_index = located[0][1] if located else 0
    for index, items in enumerate(groups):
        groups[index] = [item for item in items if not (item.get('kind') == 'curriculum'
                         and (item.get('data') or {}).get('lesson_id') == lesson_id)]

    def dependent(item):
        if item.get('kind') not in ('curriculum', 'listening', 'speaking', 'writing'):
            return False
        raw = (item.get('data') or {}).get('lesson_id')
        if not isinstance(raw, int) or isinstance(raw, bool):
            return False
        target = db.session.get(Lessons, raw)
        return target is not None and _spine_key(target) > _spine_key(phase.lesson)

    items = groups[group_index]
    prior_day = _attempt_day(user_id, phase.state, db) < get_user_local_date(user_id, db)
    section = 'required' if group_index == 0 else 'optional'
    correction = _phase_item(phase, section, first_round=False)
    if prior_day:
        # A new day's independent quotas are new work, not another cooldown.
        groups[group_index] = [correction, *items]
    else:
        first_dependent = next((i for i, item in enumerate(items) if dependent(item)), len(items))
        before, after = items[:first_dependent], items[first_dependent:]
        # A legacy snapshot may interleave lesson N+1 before reading; move only
        # its independent slots, never their state/goals, ahead of corrections.
        independent = [item for item in after if item.get('kind') in ('srs', 'reading')]
        after = [item for item in after if item.get('kind') not in ('srs', 'reading')]
        before.extend(independent)
        before.insert(min(origin_index, len(before)), _phase_item(phase, section, first_round=True))
        groups[group_index] = [*before, correction, *after]

    for items in groups:
        for item in items:
            if not item.get('completed') and dependent(item):
                item['blocked'] = True
                item.setdefault('data', {})['locked_reason'] = 'Сначала исправь ошибки предыдущего квиза'
    return groups[0], groups[1]
