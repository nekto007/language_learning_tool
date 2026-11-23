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
PASSING_SCORE_QUIZ = 50
PASSING_SCORE_FINAL_TEST = 75
QUIZ_LESSON_TYPES = frozenset({
    'grammar', 'quiz', 'ordering_quiz', 'translation_quiz',
    'listening_quiz', 'dialogue_completion_quiz',
    'audio_fill_blank', 'dictation', 'sentence_completion', 'sentence_correction',
    'collocation_matching',
})
# Compatibility name for older dictation renderers; all ordinary practice now
# follows the same 50% policy. Only the final module test keeps 75%.
PASSING_SCORE_DICTATION = PASSING_SCORE_QUIZ


def is_objective_practice(lesson: Any) -> bool:
    """Practice with an authored answer key; never self-assessment or a final."""
    kind = getattr(lesson, 'type', '') or ''
    if kind in QUIZ_LESSON_TYPES:
        return True
    content = getattr(lesson, 'content', None)
    if not isinstance(content, dict):
        return False
    if kind == 'translation':
        return content.get('mode') not in ('open', 'rubric')
    # The memory matching game has its own complete-all-pairs scoring. Authored
    # phrase quizzes use collocation_matching instead.
    if kind in ('reading', 'text', 'listening_immersion', 'listening_immersion_quiz'):
        return bool(content.get('comprehension_questions') or content.get('exercises') or content.get('questions'))
    return False


def get_lesson_passing_score(lesson: Any) -> int:
    """Return the effective passing-score threshold for ``lesson``.

    Objective practice always uses 50%; ``final_test`` always 75%.
    These owner-level policies override stale authored 70/80% settings.

    Other lesson types retain their previous resolution order:
      1. ``lesson.content['passing_score_percent']`` (preferred).
      2. ``lesson.content['passing_score']`` (legacy alias).
      3. Other non-quiz types → 70.

    Non-numeric / out-of-range overrides are ignored (fall through to the
    type default) so malformed content can't disable the threshold.
    """
    kind = getattr(lesson, 'type', '') or ''
    if kind == 'final_test':
        return PASSING_SCORE_FINAL_TEST
    if is_objective_practice(lesson):
        return PASSING_SCORE_QUIZ
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
        # Lower bound is 1, not 0 (audit E-041): a 0 override would make every
        # attempt "passing", disabling the threshold — treat it as malformed and
        # fall through to the type default, matching this docstring's promise.
        if value is not None and 1 <= value <= 100:
            return value
    if kind == 'dictation':
        return PASSING_SCORE_DICTATION
    return PASSING_SCORE_DEFAULT
