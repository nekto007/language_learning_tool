"""Pull grammar theory from grammar-lab into curriculum grammar lessons.

Given a curriculum ``Lessons`` row of type ``grammar``, resolve the
matching ``GrammarTopic`` so the lesson template can surface theory above
the exercises. Resolution is best-effort — if no topic matches, the
lesson renders as before without theory and no error is raised.

Matching strategy, in order:

1. ``Lesson.grammar_topic_id`` FK, when present (cheapest / most
   authoritative link, already used elsewhere in curriculum).
2. Case-insensitive ``GrammarTopic.title`` match on
   ``Lesson.content['topic']``, filtered to the same CEFR level as the
   lesson's module. When several topics share a title at the level, we
   take the one with the lowest ``GrammarTopic.order`` so matching is
   deterministic.

Each surfaced topic is recorded in ``GrammarTheoryView`` exactly once
per (user, lesson) pair so analytics can measure coverage without
counting revisits as views.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import func

from app.daily_plan.linear.models import GrammarTheoryView
from app.grammar_lab.models import GrammarTopic

logger = logging.getLogger(__name__)


def _lesson_level_code(lesson: Any, db: Any) -> Optional[str]:
    """Return the CEFR code for the lesson's module level, or None."""
    from app.curriculum.models import CEFRLevel, Module

    module = getattr(lesson, 'module', None)
    if module is None and lesson.module_id is not None:
        module = db.session.get(Module, lesson.module_id)
    if module is None:
        return None
    level = getattr(module, 'level', None)
    if level is None and module.level_id is not None:
        level = db.session.get(CEFRLevel, module.level_id)
    return getattr(level, 'code', None) if level is not None else None


def _resolve_topic(lesson: Any, db: Any) -> Optional[GrammarTopic]:
    """Find the GrammarTopic linked to a curriculum grammar lesson.

    Returns None when the lesson has no usable hint (missing FK + missing
    ``content['topic']``) or when no topic matches the title/level pair.
    """
    if getattr(lesson, 'grammar_topic_id', None):
        topic = db.session.get(GrammarTopic, lesson.grammar_topic_id)
        if topic is not None:
            return topic

    content = lesson.content if isinstance(lesson.content, dict) else None
    topic_hint = content.get('topic') if content else None
    if not isinstance(topic_hint, str) or not topic_hint.strip():
        return None

    level_code = _lesson_level_code(lesson, db)
    query = db.session.query(GrammarTopic).filter(
        func.lower(GrammarTopic.title) == topic_hint.strip().lower()
    )
    if level_code:
        query = query.filter(GrammarTopic.level == level_code)

    return query.order_by(GrammarTopic.order.asc(), GrammarTopic.id.asc()).first()


def _existing_view(user_id: int, lesson_id: int, db: Any) -> Optional[GrammarTheoryView]:
    return (
        db.session.query(GrammarTheoryView)
        .filter(
            GrammarTheoryView.user_id == user_id,
            GrammarTheoryView.lesson_id == lesson_id,
        )
        .order_by(GrammarTheoryView.shown_at.asc(), GrammarTheoryView.id.asc())
        .first()
    )


def get_theory_for_lesson(
    user_id: int,
    lesson: Any,
    db: Any,
    *,
    commit: bool = False,
) -> Optional[GrammarTopic]:
    """Return the theory topic to show above a grammar lesson's exercises.

    Logs a ``GrammarTheoryView`` row on the first visit for this
    (user, lesson) pair. Revisits re-use the original row and do not
    create duplicates.

    ``commit=False`` (default) flushes the new view row but lets the
    caller own the transaction — matches the grammar lesson controller,
    which commits once after progress updates.
    """
    if lesson is None or getattr(lesson, 'type', None) != 'grammar':
        return None

    try:
        topic = _resolve_topic(lesson, db)
    except Exception:  # noqa: BLE001 — never break grammar rendering on a DB hiccup
        logger.exception('grammar_theory: topic lookup failed for lesson=%s', lesson.id)
        return None

    if topic is None:
        return None

    existing = _existing_view(user_id, lesson.id, db)
    if existing is None:
        savepoint = db.session.begin_nested()
        try:
            view = GrammarTheoryView(
                user_id=user_id,
                topic_id=topic.id,
                lesson_id=lesson.id,
            )
            db.session.add(view)
            savepoint.commit()
            if commit:
                db.session.commit()
            else:
                db.session.flush()
        except Exception:  # noqa: BLE001 — savepoint scopes the rollback, outer tx untouched
            logger.exception(
                'grammar_theory: failed to record view user=%s lesson=%s topic=%s',
                user_id, lesson.id, topic.id,
            )
            try:
                savepoint.rollback()
            except Exception:  # noqa: BLE001
                pass

    return topic
