"""Compact grammar reminder shown before the exercises of a module (2026-09-06).

The module's grammar lesson (position 4) carries the full theory: five
sections and ~5 000 characters on average. Showing that again before every
later lesson would drive learners away; showing nothing lets the rule fade
by lesson 10. From :data:`DIGEST_FROM_LESSON` on, the lesson page gets a
digest built from the grammar lesson's own content: the one-sentence
``rule``, up to three ``important_notes`` and up to three example rows —
no separate authoring. When the learner's accuracy on the module's grammar
topic is weak (the same signal the daily plan uses for its hint), the
digest is flagged and its examples are opened, so a struggling learner
meets the rule before the next exercise.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import url_for

from app.curriculum.models import Lessons
from app.utils.db import db as _db

logger = logging.getLogger(__name__)

DIGEST_FROM_LESSON = 6
MAX_EXAMPLES = 3
MAX_NOTES = 3
_TITLE_PREFIX = 'Грамматика: '


def _examples_from_content(content: dict[str, Any]) -> list[dict[str, str]]:
    """Up to MAX_EXAMPLES (en, ru) pairs from the sections' tables / example lists."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(en: Any, ru: Any) -> None:
        en_s = str(en or '').strip()
        if not en_s or en_s in seen or len(out) >= MAX_EXAMPLES:
            return
        seen.add(en_s)
        out.append({'en': en_s, 'ru': str(ru or '').strip()})

    for section in content.get('sections') or []:
        if not isinstance(section, dict):
            continue
        for row in section.get('table') or []:
            if isinstance(row, dict) and row.get('example'):
                _add(row.get('example'), row.get('translation') or row.get('example_translation'))
        for ex in section.get('examples') or []:
            if isinstance(ex, dict):
                _add(ex.get('english') or ex.get('example'), ex.get('russian') or ex.get('translation'))
        if len(out) >= MAX_EXAMPLES:
            break
    for ex in content.get('examples') or []:
        if isinstance(ex, dict):
            _add(ex.get('english') or ex.get('example'), ex.get('russian') or ex.get('translation'))
    return out[:MAX_EXAMPLES]


def _module_grammar_lesson(module_id: int, before_number: int | None = None) -> Lessons | None:
    """The grammar lesson whose theory the current lesson practises.

    With one grammar lesson per module (the whole corpus today) this is it.
    Should a module ever carry several, the nearest one *before* the current
    lesson wins; a lesson ahead of every grammar lesson gets the first
    (Codex review, 2026-09-06).
    """
    query = Lessons.query.filter_by(module_id=module_id, type='grammar')
    if before_number is not None:
        preceding = query.filter(Lessons.number < before_number).order_by(Lessons.number.desc()).first()
        if preceding is not None:
            return preceding
    return query.order_by(Lessons.number).first()


def _topic_is_weak(user_id: int, topic_id: int, db: Any) -> bool:
    from app.daily_plan.items.curriculum import _get_weak_grammar_topic_ids

    # One topic, not the user's whole grammar history: this runs on every
    # lesson page (Codex review, 2026-09-06).
    return int(topic_id) in _get_weak_grammar_topic_ids(user_id, db, topic_ids=[int(topic_id)])


def build_grammar_digest(lesson: Any, user_id: int | None = None, db: Any = None) -> dict[str, Any] | None:
    """Digest dict for ``lesson``'s page, or None when the page should show nothing.

    Nothing is shown before :data:`DIGEST_FROM_LESSON`, on the grammar lesson
    itself, or for a module without a grammar lesson / without digestible
    content. ``weak`` needs ``user_id``; a failure of that (optional) signal
    never hides the digest.
    """
    if lesson is None or getattr(lesson, 'type', None) == 'grammar':
        return None
    if int(getattr(lesson, 'number', 0) or 0) < DIGEST_FROM_LESSON:
        return None
    module_id = getattr(lesson, 'module_id', None)
    if module_id is None:
        return None
    grammar = _module_grammar_lesson(module_id, before_number=int(getattr(lesson, 'number', 0) or 0))
    if grammar is None:
        return None
    content = grammar.content if isinstance(grammar.content, dict) else {}
    rule = str(content.get('rule') or '').strip()
    notes = [str(n).strip() for n in (content.get('important_notes') or []) if str(n).strip()][:MAX_NOTES]
    examples = _examples_from_content(content)
    if not (rule or notes or examples):
        return None
    title = (grammar.title or '').removeprefix(_TITLE_PREFIX).strip() or str(content.get('title') or '')
    weak = False
    topic_id = getattr(grammar, 'grammar_topic_id', None)
    if user_id is not None and topic_id:
        try:
            weak = _topic_is_weak(user_id, int(topic_id), db or _db)
        except Exception:
            logger.warning("grammar digest: weak-topic check failed user=%s topic=%s", user_id, topic_id, exc_info=True)
    practice_url = None
    if topic_id:
        try:
            practice_url = url_for('grammar_lab.topic_detail_legacy', topic_id=int(topic_id))
        except Exception:
            practice_url = None
    return {
        'title': title,
        'rule': rule,
        'notes': notes,
        'examples': examples,
        'weak': weak,
        'lesson_number': grammar.number,
        'theory_url': url_for('learn.lesson_by_id', lesson_id=grammar.id),
        'practice_url': practice_url,
    }


def grammar_digest_for_template(lesson: Any) -> dict[str, Any] | None:
    """Jinja global: digest for the current viewer, never raising into a template."""
    try:
        from flask_login import current_user

        user_id = current_user.id if getattr(current_user, 'is_authenticated', False) else None
        return build_grammar_digest(lesson, user_id=user_id)
    except Exception:
        logger.warning("grammar digest failed for lesson=%s", getattr(lesson, 'id', None), exc_info=True)
        return None
