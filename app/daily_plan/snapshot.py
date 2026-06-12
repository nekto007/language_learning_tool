"""Daily required-plan snapshot: «железный» состав плана на день.

План пересобирается на каждый запрос, поэтому без фиксации состав
required-секции мог меняться в течение дня: слоты исчезали/появлялись,
deck-quiz подменял SRS после прохождения урока, цель SRS таяла по мере
ревью. Снапшот решает это так:

- При ПЕРВОЙ сборке за локальный день состав required (id, kind, порядок,
  eta, замороженная SRS-цель) сохраняется в ``DailyPlanLog.plan_json``.
- Последующие сборки реконсилируются со снапшотом: состав и порядок — из
  снапшота, а сами карточки (completion, счётчики, url, skip-state) —
  живые, из свежей сборки.

Правила reconcile:

- Свежий item сопоставляется со слотом снапшота по ``id``, иначе по
  ``kind`` (первый не занятый). Kind-матч покрывает легитимные подмены:
  skip урока (новый lesson_id), deck-quiz ↔ srs:global.
- Слот снапшота без свежей пары = слот исчез из сборки (источник
  удовлетворён или более не применим). Он остаётся в required как
  completed-карточка (``data.snapshot_carried=True``) — состав дня не
  сжимается, day_secured-семантика эквивалентна свежей сборке (свежая
  сборка тоже его не требует).
- Свежие items, не вошедшие в снапшот (kind появился среди дня, например
  listening после перехода спайна в новый модуль), required НЕ растят —
  они переезжают в начало optional. Завтра попадут в required штатно.
- SRS-слот получает ``data.goal_total`` — замороженный дневной объём
  (см. ``_srs_goal_total``), чтобы «12 из 30» не превращалось в «12 из 18»
  по мере ревью.

Запись flush-only в savepoint'е (race-safe по
``uq_daily_plan_log_user_date``, как ``write_secured_at``); коммитит
вызывающий. GET-потоки, которые не коммитят, просто пересоздадут снапшот
при следующем закоммиченном запросе — данные от этого не портятся.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1


def _srs_goal_total(data: dict[str, Any]) -> Optional[int]:
    """Frozen daily SRS goal = ещё показываемое + уже сделанное сегодня."""
    if 'total_show' in data:
        total = (
            int(data.get('total_show') or 0)
            + int(data.get('reviews_today') or 0)
            + int(data.get('new_today') or 0)
        )
        return total if total > 0 else None
    if 'word_limit' in data:  # deck-quiz variant
        limit = int(data.get('word_limit') or 0)
        return limit if limit > 0 else None
    return None


def _slot_from_item(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get('data') or {}
    slot: dict[str, Any] = {
        'id': item.get('id'),
        'kind': item.get('kind'),
        'title': item.get('title'),
        'subtitle': item.get('subtitle'),
        'lesson_type': item.get('lesson_type'),
        'eta_minutes': int(item.get('eta_minutes') or 0),
    }
    if item.get('kind') == 'srs':
        slot['srs_goal_total'] = _srs_goal_total(data)
    return slot


def _carried_item(slot: dict[str, Any]) -> dict[str, Any]:
    """Completed-карточка для слота, исчезнувшего из свежей сборки."""
    return {
        'id': slot.get('id'),
        'section': 'required',
        'kind': slot.get('kind'),
        'title': slot.get('title'),
        'subtitle': slot.get('subtitle'),
        'lesson_type': slot.get('lesson_type'),
        'eta_minutes': 0,
        'url': None,
        'completed': True,
        'completion_signal': 'none',
        'data': {'snapshot_carried': True},
    }


def _valid_snapshot(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict) or raw.get('version') != SNAPSHOT_VERSION:
        return None
    slots = raw.get('slots')
    if not isinstance(slots, list) or not slots:
        return None
    for slot in slots:
        if not isinstance(slot, dict) or not slot.get('id') or not slot.get('kind'):
            return None
    return raw


def _get_or_create_log_row(user_id: int, plan_date: Any, db: Any):
    """Race-safe get-or-create по uq_daily_plan_log_user_date (flush-only)."""
    from sqlalchemy.exc import IntegrityError

    from app.daily_plan.models import DailyPlanLog

    log = (
        db.session.query(DailyPlanLog)
        .filter_by(user_id=user_id, plan_date=plan_date)
        .first()
    )
    if log is None:
        log = DailyPlanLog(user_id=user_id, plan_date=plan_date)
        db.session.add(log)
        try:
            with db.session.begin_nested():
                db.session.flush()
        except IntegrityError:
            log = (
                db.session.query(DailyPlanLog)
                .filter_by(user_id=user_id, plan_date=plan_date)
                .first()
            )
    return log


def reconcile_required_with_snapshot(
    user_id: int,
    required_dicts: list[dict[str, Any]],
    db: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pin состава required к дневному снапшоту.

    Возвращает ``(required, demoted)``: required в составе/порядке снапшота
    и свежие items, не вошедшие в него (caller добавляет их в optional).
    Best-effort: любая ошибка → исходный required без изменений.
    """
    try:
        from app.utils.time_utils import get_user_local_date

        today = get_user_local_date(user_id, db)
        log = _get_or_create_log_row(user_id, today, db)
        if log is None:  # обе попытки get-or-create не удались
            return required_dicts, []

        snap = _valid_snapshot(log.plan_json)
        if snap is None:
            if not required_dicts:
                # Пустой required не фиксируем: план мог собраться в
                # вырожденном состоянии (нет контента/онбординг не завершён),
                # снапшот зафиксировал бы пустой день навсегда.
                return required_dicts, []
            slots = [_slot_from_item(it) for it in required_dicts]
            log.plan_json = {
                'version': SNAPSHOT_VERSION,
                'date': today.isoformat(),
                'slots': slots,
            }
            db.session.flush()
            # goal_total доступен с первого же запроса дня, не только после
            # повторной сборки — иначе «12 из 30» появлялось бы со 2-го визита.
            for slot, item in zip(slots, required_dicts):
                if slot.get('kind') == 'srs' and slot.get('srs_goal_total'):
                    item.setdefault('data', {})['goal_total'] = slot['srs_goal_total']
            return required_dicts, []

        fresh_by_id: dict[str, dict[str, Any]] = {
            it['id']: it for it in required_dicts if it.get('id')
        }
        consumed: set[str] = set()
        reconciled: list[dict[str, Any]] = []

        def _match(slot: dict[str, Any]) -> Optional[dict[str, Any]]:
            item = fresh_by_id.get(slot['id'])
            if item is not None and item['id'] not in consumed:
                return item
            for candidate in required_dicts:
                if candidate.get('id') in consumed:
                    continue
                if candidate.get('kind') == slot.get('kind'):
                    return candidate
            return None

        for slot in snap['slots']:
            item = _match(slot)
            if item is not None:
                consumed.add(item['id'])
                if slot.get('kind') == 'srs' and slot.get('srs_goal_total'):
                    item.setdefault('data', {})['goal_total'] = slot['srs_goal_total']
                reconciled.append(item)
            else:
                reconciled.append(_carried_item(slot))

        demoted = [
            it for it in required_dicts
            if it.get('id') and it['id'] not in consumed
        ]
        if demoted:
            logger.info(
                "plan_snapshot user=%s demoted=%s — required не растёт среди дня",
                user_id, [it['id'] for it in demoted],
            )
        return reconciled, demoted
    except Exception:
        logger.warning(
            "plan_snapshot reconcile failed for user=%s — using fresh plan",
            user_id, exc_info=True,
        )
        return required_dicts, []
