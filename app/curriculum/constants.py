"""Passing-score thresholds and the single helper that resolves the
effective threshold for a lesson.

Centralising this avoids the bug class where the grader and the DB-write
side use *different* thresholds — e.g. grader returns ``passed=True`` at
score 79 (default 70) while ``update_progress_with_grading`` is called
with the lesson's stricter ``content['passing_score_percent']=80`` and
writes ``status='in_progress'``. Frontend says "passed", DB disagrees,
user gets stuck.

Every route that submits to ``ProgressService.update_progress_with_grading``
should compute the threshold once via ``get_lesson_passing_score(lesson)``
and pass the same value to BOTH the grader and the service.
"""
from __future__ import annotations

from typing import Any

PASSING_SCORE_DEFAULT = 70
PASSING_SCORE_DICTATION = 80


def get_lesson_passing_score(lesson: Any) -> int:
    """Return the effective passing-score threshold for ``lesson``.

    Resolution order:
      1. ``lesson.content['passing_score_percent']`` (preferred).
      2. ``lesson.content['passing_score']`` (legacy alias).
      3. Type default: ``dictation`` → 80, everything else → 70.

    Non-numeric / out-of-range overrides are ignored (fall through to the
    type default) so malformed content can't disable the threshold.
    """
    content = getattr(lesson, 'content', None)
    if not isinstance(content, dict):
        content = {}
    explicit = content.get('passing_score_percent')
    if explicit is None:
        explicit = content.get('passing_score')
    if explicit is not None:
        try:
            value = int(explicit)
        except (TypeError, ValueError):
            value = None
        if value is not None and 0 <= value <= 100:
            return value
    if (getattr(lesson, 'type', '') or '') == 'dictation':
        return PASSING_SCORE_DICTATION
    return PASSING_SCORE_DEFAULT
