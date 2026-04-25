"""Schema validation for ``GrammarExercise.content``.

Each exercise type has a minimum payload required for the grader to evaluate
answers. Without that data the grader silently returns ``is_correct=False`` for
every input, which masks broken seed/import data. ``validate_exercise_content``
raises ``ValueError`` when the payload is missing the keys the grader needs.
"""

from __future__ import annotations

from typing import Any, Mapping


_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    'fill_blank': ('correct_answer',),
    'multiple_choice': ('correct_answer', 'options'),
    'reorder': ('correct_answer',),
    'transformation': ('correct_answer',),
    'error_correction': ('correct_answer',),
    'translation': ('correct_answer',),
    'true_false': ('correct_answer',),
    'matching': ('pairs',),
}


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (str, list, tuple, dict)):
        return len(value) > 0
    return True


def validate_exercise_content(exercise_type: str, content: Mapping[str, Any] | None) -> None:
    """Raise ``ValueError`` if ``content`` is missing keys required for the type.

    Unknown exercise types are accepted (forward-compat with new types).
    """
    required = _REQUIRED_KEYS.get(exercise_type)
    if required is None:
        return
    if not isinstance(content, Mapping):
        raise ValueError(
            f"GrammarExercise[{exercise_type}] content must be a mapping, got {type(content).__name__}"
        )
    missing = [key for key in required if not _is_present(content.get(key))]
    if missing:
        raise ValueError(
            f"GrammarExercise[{exercise_type}] content missing required key(s): {', '.join(missing)}"
        )
