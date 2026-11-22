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
})
# 75, not 80 (lesson audit 2026-09-05, B11): 52 of 86 dictations are a
# 4-gap cloze, and at 80 % the only passing outcome was 4/4 — the threshold
# shown to the learner was a lie. At 75 one miss passes (3/4, 4/5) while the
# bar stays above the quizzes' 50. The owner's call: «не надо быть слишком
# строгими, иначе будут убегать и не завершать».
PASSING_SCORE_DICTATION = 75


def get_lesson_passing_score(lesson: Any) -> int:
    """Return the effective passing-score threshold for ``lesson``.

    Ordinary quiz/grammar lessons always use 50%; ``final_test`` always 75%.
    These owner-level policies override stale authored 70/80% settings.

    Other lesson types retain their previous resolution order:
      1. ``lesson.content['passing_score_percent']`` (preferred).
      2. ``lesson.content['passing_score']`` (legacy alias).
      3. Type default: ``dictation`` → 75, other non-quiz types → 70.

    Non-numeric / out-of-range overrides are ignored (fall through to the
    type default) so malformed content can't disable the threshold.
    """
    kind = getattr(lesson, 'type', '') or ''
    if kind == 'final_test':
        return PASSING_SCORE_FINAL_TEST
    if kind in QUIZ_LESSON_TYPES:
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
