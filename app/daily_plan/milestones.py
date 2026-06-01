"""Milestone emitters for the unified daily plan.

A milestone is a real user achievement: day completed, module completed,
level completed, book completed. Each event:

- Fires once per (user, target) via an idempotent Notification check.
- Posts a ``Notification`` with ``type='milestone'`` so the dashboard
  popup picks it up via the existing unread-notifications mechanism.
- Does NOT become a permanent card in the daily plan payload — these
  are transient celebrations, dismissed after display.

The ``daily_plan_completed`` event additionally reuses the existing
``DailyPlanEvent('minimum_completed')`` row for per-day idempotency.

These emitters are intentionally tolerant of failures: a milestone toast
is a nice-to-have, never block the main user flow. Callers wrap us in
try/except and roll back on error.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = 'milestone'


def _notification_exists(user_id: int, link: str, db: Any) -> bool:
    """Return True when a milestone notification with this link already exists."""
    from app.notifications.models import Notification

    return (
        db.session.query(Notification.id)
        .filter(
            Notification.user_id == user_id,
            Notification.type == NOTIFICATION_TYPE,
            Notification.link == link,
        )
        .first()
        is not None
    )


def emit_daily_plan_completed(user_id: int, plan_date: _date, db: Any) -> bool:
    """Emit a milestone notification when the user closes the day.

    Idempotent per (user, plan_date) via the ``DailyPlanEvent('minimum_completed')``
    row that is written by ``emit_minimum_completed``. Safe to call from
    every ``/api/daily-status`` request — if minimum_completed already
    exists for today, no notification is created.

    Caller commits.
    """
    from app.daily_plan.models import DailyPlanEvent
    from app.notifications.services import create_notification

    already_completed_today = (
        db.session.query(DailyPlanEvent.id)
        .filter(
            DailyPlanEvent.user_id == user_id,
            DailyPlanEvent.event_type == 'minimum_completed',
            DailyPlanEvent.plan_date == plan_date,
        )
        .first()
        is not None
    )
    link = f'/dashboard#day-secured-{plan_date.isoformat()}'
    if already_completed_today and _notification_exists(user_id, link, db):
        return False

    create_notification(
        user_id=user_id,
        type=NOTIFICATION_TYPE,
        title='План дня выполнен',
        message='Ты закрыл обязательный минимум — день в копилке.',
        link=link,
        icon='🎯',
    )
    logger.info("milestone user=%s event=daily_plan_completed date=%s", user_id, plan_date)
    return True


def emit_module_completed(user_id: int, module_id: int, db: Any) -> bool:
    """Emit when the user completes the final lesson in a module.

    Caller must verify that all lessons of the module are completed before
    calling — this helper trusts the precondition and only handles the
    notification side. Idempotent per (user, module).
    """
    from app.curriculum.models import Module
    from app.notifications.services import create_notification

    link = f'/learn/module/{module_id}'
    if _notification_exists(user_id, link, db):
        return False

    module = db.session.get(Module, module_id)
    title = f'Модуль пройден: {module.title}' if module is not None else 'Модуль пройден'

    create_notification(
        user_id=user_id,
        type=NOTIFICATION_TYPE,
        title=title,
        message='Все уроки модуля завершены.',
        link=link,
        icon='📘',
    )
    logger.info("milestone user=%s event=module_completed module=%s", user_id, module_id)
    return True


def emit_level_completed(user_id: int, level_code: str, db: Any) -> bool:
    """Emit when the user completes the final module of a CEFR level.

    Idempotent per (user, level_code).
    """
    from app.notifications.services import create_notification

    link = f'/learn/level/{level_code}'
    if _notification_exists(user_id, link, db):
        return False

    create_notification(
        user_id=user_id,
        type=NOTIFICATION_TYPE,
        title=f'Уровень {level_code} пройден',
        message='Все модули уровня завершены. Открыт следующий уровень.',
        link=link,
        icon='🎓',
    )
    logger.info("milestone user=%s event=level_completed level=%s", user_id, level_code)
    return True


def emit_book_completed(user_id: int, book_id: int, db: Any) -> bool:
    """Emit when the user finishes a book (reading progress reaches 100%).

    Idempotent per (user, book).
    """
    from app.books.models import Book
    from app.notifications.services import create_notification

    link = f'/books/{book_id}'
    if _notification_exists(user_id, link, db):
        return False

    book = db.session.get(Book, book_id)
    title = f'Книга прочитана: {book.title}' if book is not None else 'Книга прочитана'

    create_notification(
        user_id=user_id,
        type=NOTIFICATION_TYPE,
        title=title,
        message='Поздравляем! Книга прочитана до конца.',
        link=link,
        icon='📖',
    )
    logger.info("milestone user=%s event=book_completed book=%s", user_id, book_id)
    return True


def check_curriculum_milestones(user_id: int, lesson_id: int, db: Any) -> None:
    """Inspect lesson completion → emit module/level milestones if applicable.

    Called after a curriculum lesson is marked completed. Walks the
    lesson's module to see whether the user just closed the module, and
    if so, whether they also closed the level.

    Failures are logged and swallowed — milestones are non-critical.
    """
    try:
        from app.curriculum.models import CEFRLevel, LessonProgress, Lessons, Module

        lesson = db.session.get(Lessons, lesson_id)
        if lesson is None or lesson.module_id is None:
            return
        module_id = lesson.module_id

        module_lesson_ids = [
            lid for (lid,) in db.session.query(Lessons.id)
            .filter(Lessons.module_id == module_id)
            .all()
        ]
        if not module_lesson_ids:
            return

        completed_count = (
            db.session.query(LessonProgress.id)
            .filter(
                LessonProgress.user_id == user_id,
                LessonProgress.status == 'completed',
                LessonProgress.lesson_id.in_(module_lesson_ids),
            )
            .count()
        )
        if completed_count < len(module_lesson_ids):
            return

        emit_module_completed(user_id, module_id, db)

        module = db.session.get(Module, module_id)
        if module is None or module.level_id is None:
            return
        level = db.session.get(CEFRLevel, module.level_id)
        if level is None:
            return

        level_module_ids = [
            mid for (mid,) in db.session.query(Module.id)
            .filter(Module.level_id == module.level_id)
            .all()
        ]
        if not level_module_ids:
            return

        level_lesson_ids = [
            lid for (lid,) in db.session.query(Lessons.id)
            .filter(Lessons.module_id.in_(level_module_ids))
            .all()
        ]
        if not level_lesson_ids:
            return

        level_completed_count = (
            db.session.query(LessonProgress.id)
            .filter(
                LessonProgress.user_id == user_id,
                LessonProgress.status == 'completed',
                LessonProgress.lesson_id.in_(level_lesson_ids),
            )
            .count()
        )
        if level_completed_count >= len(level_lesson_ids):
            emit_level_completed(user_id, level.code, db)
    except Exception:
        logger.warning("check_curriculum_milestones failed for user=%s lesson=%s",
                       user_id, lesson_id, exc_info=True)


def check_book_milestone(user_id: int, book_id: int, percent: float, db: Any) -> None:
    """Emit book_completed milestone when book reaches 100%.

    Called from ``compute_book_progress_percent`` (or a hook around it).
    Failures swallowed.
    """
    try:
        if percent >= 100.0:
            emit_book_completed(user_id, book_id, db)
    except Exception:
        logger.warning("check_book_milestone failed for user=%s book=%s",
                       user_id, book_id, exc_info=True)


__all__ = [
    'emit_daily_plan_completed',
    'emit_module_completed',
    'emit_level_completed',
    'emit_book_completed',
    'check_curriculum_milestones',
    'check_book_milestone',
]
