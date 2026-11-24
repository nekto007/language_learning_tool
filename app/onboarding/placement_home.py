"""Voluntary diagnostic invitations, never a daily-plan prerequisite."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, case
from sqlalchemy.exc import IntegrityError

from app.onboarding.placement_models import PlacementAttempt, PlacementBank, PlacementPreference, utcnow
from app.onboarding.placement_engine import LEVELS, PlacementError
from app.utils.db import db


def _preference(user_id: int) -> PlacementPreference:
    row = db.session.get(PlacementPreference, user_id)
    if row is None:
        try:
            with db.session.begin_nested():
                row = PlacementPreference(user_id=user_id, level_checkpoints={})
                db.session.add(row)
                db.session.flush()
        except IntegrityError:
            row = db.session.get(PlacementPreference, user_id)
            if row is None:
                raise
    return row


def _completed_levels(user_id: int) -> list[tuple[str, datetime]]:
    from app.curriculum.models import CEFRLevel, Module, Lessons, LessonProgress

    rows = (
        db.session.query(
            CEFRLevel.code,
            func.count(Lessons.id),
            func.sum(case((LessonProgress.status == "completed", 1), else_=0)),
            func.max(LessonProgress.completed_at),
        )
        .select_from(CEFRLevel)
        .join(Module)
        .join(Lessons)
        .outerjoin(LessonProgress, (LessonProgress.lesson_id == Lessons.id) & (LessonProgress.user_id == user_id))
        .filter(CEFRLevel.code.in_(LEVELS))
        .group_by(CEFRLevel.id)
        .order_by(CEFRLevel.order.desc())
        .all()
    )
    return [
        (code, stamp.replace(tzinfo=None))
        for code, total, completed, stamp in rows
        if total > 0 and completed == total and stamp is not None
    ]


def _dismissed(row: PlacementPreference | None, key: str) -> bool:
    return row is not None and (row.dismissed_key == key or key in (row.dismissed_keys or []))


def invitation(user_id: int) -> dict[str, Any] | None:
    from flask import has_app_context

    if not has_app_context() or type(user_id) is not int:
        return None
    active = PlacementAttempt.query.filter_by(user_id=user_id, status="active").first()
    if active:
        saved = db.session.get(PlacementPreference, user_id)
        if _dismissed(saved, "resume:" + active.id):
            return None
        return {
            "key": "resume:" + active.id,
            "kind": "resume",
            "title": "Продолжим проверку уровня?",
            "body": f"Сохранено ответов: {sum('correct' in q for q in active.state['asked'])}. Можно продолжить с того же задания.",
            "cta": "Продолжить тест",
            "url": "/placement",
        }
    if not db.session.query(PlacementBank.id).filter_by(active=True).first():
        return None
    latest = (
        PlacementAttempt.query.filter_by(user_id=user_id, status="completed")
        .order_by(PlacementAttempt.completed_at.desc())
        .first()
    )
    preference = _preference(user_id)
    if latest and not latest.applied_at:
        card = {
            "key": "result:" + latest.id,
            "kind": "result",
            "title": "Результат проверки готов",
            "body": f"Рекомендуем начать с {latest.result['recommended_level']}. Ты сам выбираешь, применять ли рекомендацию.",
            "cta": "Посмотреть результат",
            "url": "/placement?result=1",
        }
    else:
        checkpoints = dict(preference.level_checkpoints or {})
        checkpoint = None
        for code, stamp in _completed_levels(user_id):
            checkpoints.setdefault(code, stamp.isoformat())
            if latest is None or latest.completed_at < datetime.fromisoformat(checkpoints[code]):
                checkpoint = code
                break
        if checkpoints != preference.level_checkpoints:
            preference.level_checkpoints = checkpoints
            db.session.flush()
        if checkpoint:
            card = {
                "key": "level:" + checkpoint,
                "kind": "checkpoint",
                "title": f"{checkpoint} завершён — проверим знания?",
                "body": "Уточним, что уже получается и что стоит закрепить. Следующий уровень доступен независимо от проверки.",
                "cta": "Пройти рекомендуемую проверку",
                "url": "/placement",
            }
        elif latest is None:
            card = {
                "key": "initial",
                "kind": "initial",
                "title": "Уже учил английский? Подберём подходящий старт",
                "body": "Быстрый или подробный тест без говорения. Можно пройти сейчас или вернуться позже.",
                "cta": "Подобрать уровень",
                "url": "/placement",
            }
        else:
            return None
    return None if _dismissed(preference, card["key"]) else card


def dismiss(user_id: int, key: Any) -> None:
    card = invitation(user_id)
    if not isinstance(key, str) or card is None or card["key"] != key:
        raise PlacementError("invitation_changed", 409)
    row = _preference(user_id)
    row.dismissed_key = key
    row.dismissed_keys = [value for value in (row.dismissed_keys or []) if value != key][-49:] + [key]
    row.dismissed_at = utcnow()
    db.session.flush()
