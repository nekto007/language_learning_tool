"""Versioned, owner-approved grading corrections for standalone Grammar Lab exercises."""
from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from typing import Any

from app.curriculum.answer_review_edits import ALIAS_FIELDS, replace_text_key
from app.grammar_lab.content_catalog import content_digest
from app.grammar_lab.models import GrammarExercise
from app.grammar_lab.services.grader import GrammarExerciseGrader

LAB_GRADER_VERSION = 1
TEXT_TYPES = {'fill_blank', 'translation', 'transformation', 'error_correction'}


def _revision(exercise: GrammarExercise, row: dict) -> str:
    # The compiler stamps every exercise with the digest of the entire topic.
    material = {k: v for k, v in row.items() if k != 'guided_revision'}
    return content_digest([exercise.topic_id, exercise.exercise_type, material])


def effective_content(exercise: GrammarExercise) -> dict:
    """Keep the authored catalog intact and expire the correction when the source changes."""
    raw = exercise.content
    override = getattr(exercise, 'answer_review_override', None)
    if (not isinstance(override, dict) or override.get('source_revision') != _revision(exercise, raw)
            or override.get('grader_version') != LAB_GRADER_VERSION):
        return raw
    patch = override.get('patch')
    if not isinstance(patch, dict) or not patch.keys() <= {'correct_answer', 'correct_index', *ALIAS_FIELDS}:
        return raw
    effective = {**raw, **patch}
    if 'correct_answer' in patch and 'answer' in raw and raw['answer'] == raw.get('correct_answer'):
        effective['answer'] = patch['correct_answer']
    return effective


def lab_revision(exercise: GrammarExercise) -> str:
    return _revision(exercise, effective_content(exercise))


def grade_row(exercise: GrammarExercise, row: dict, answer: Any) -> dict:
    view = SimpleNamespace(id=exercise.id, exercise_type=exercise.exercise_type, content=row)
    return GrammarExerciseGrader().grade(view, answer)


def display_review_answers(exercise: GrammarExercise, row: dict, result: dict) -> tuple[Any, Any]:
    """Show the words paired by the learner in place of browser option indexes."""
    shown, expected = result['user_answer'], result['correct_answer']
    if exercise.exercise_type == 'matching':
        from app.grammar_lab.dispute_receipts import normalized_lab_answer

        mapping = normalized_lab_answer(exercise, shown)
        pairs = row.get('pairs', [])
        if isinstance(mapping, dict) and all(isinstance(pair, dict) for pair in pairs):
            left = [p.get('english') or p.get('left') for p in pairs]
            right = [p.get('russian') or p.get('right') for p in pairs]
            if all(left) and all(right):
                shown = '\n'.join(f'{word} → {right[mapping[str(i)]]}' for i, word in enumerate(left))
                expected = '\n'.join(f'{a} → {b}' for a, b in zip(left, right, strict=True))
    return shown, expected


def _uses_all_tiles(words: Any, sentence: str) -> bool:
    """Prove that the submitted text can be assembled from the displayed tiles."""
    if not isinstance(words, list) or not words or not all(isinstance(w, str) and w.strip() for w in words):
        return False
    available = Counter(w.strip().casefold() for w in words)
    # Preserve phrase tiles (e.g. "in the") and repeated words. A partial or
    # ambiguous reconstruction may go to an editor, never straight to a patch.
    labels = sorted(available, key=len, reverse=True)
    remaining = sentence.strip().casefold()
    for _ in words:
        tile = next((label for label in labels if available[label]
                     and (remaining == label or remaining.startswith(label + ' '))), None)
        if tile is None:
            return False
        remaining = remaining[len(tile):].lstrip()
        available[tile] -= 1
    return not remaining


def proposed_lab_edit(exercise: GrammarExercise, row: dict, answer: Any, label: str) -> dict | None:
    if label not in {'valid_variant', 'wrong_key'}:
        return None

    def accepted(candidate: dict, value: Any) -> bool:
        return grade_row(exercise, candidate, value).get('is_correct') is True

    if exercise.exercise_type == 'multiple_choice' and label == 'wrong_key':
        from app.curriculum.grading import _quiz_option_index

        options = row.get('options')
        if (not isinstance(options, list) or not 2 <= len(options) <= 12
                or not all(isinstance(choice, str) and choice.strip() for choice in options)
                or len(set(options)) != len(options)):
            return None
        index = _quiz_option_index(options, answer)
        keys = [k for k in ('correct_answer', 'correct_index') if k in row]
        if index < 0 or len(keys) != 1:
            return None
        key = keys[0]
        patch = {key: index if key == 'correct_index' or type(row[key]) is int else options[index]}
        before = [i for i in range(len(options)) if accepted(row, i)]
        after = [i for i in range(len(options)) if accepted({**row, **patch}, i)]
        return patch if len(before) == 1 and index not in before and after == [index] else None

    if exercise.exercise_type == 'true_false' and label == 'wrong_key':
        choice = GrammarExerciseGrader._boolean_answer(answer)
        if choice is None or accepted(row, answer):
            return None
        patch = {'correct_answer': choice}
        return patch if accepted({**row, **patch}, answer) else None
    if exercise.exercise_type == 'reorder':
        if not isinstance(answer, (str, list)):
            return None
        if isinstance(answer, list):
            # The grader requires each authored index exactly once, even for identical tiles.
            answer = grade_row(exercise, row, answer).get('user_answer')
        elif len(answer) > 500 or not _uses_all_tiles(row.get('words'), answer):
            return None
    elif exercise.exercise_type not in TEXT_TYPES:
        return None
    original = row.get('correct_answer')
    if (not isinstance(original, str) or not original.strip()
            or not isinstance(answer, str) or not answer.strip() or len(answer) > 500
            or not answer.isprintable() or '<' in answer or '>' in answer):
        return None
    if label == 'valid_variant':
        aliases = row.get('alternatives', [])
        if not isinstance(aliases, list) or accepted(row, answer):
            return None
        patch = {'alternatives': [*aliases, answer]}
    else:
        # A correction with separate word/sentence keys needs an editor to reconcile both.
        if row.get('correct_sentence') or row.get('full_correct'):
            return None
        patch = replace_text_key(row, 'correct_answer', answer)
    after = {**row, **patch}
    if not accepted(after, answer) or accepted(after, original) != (label == 'valid_variant'):
        return None
    return patch


def apply_lab_patch(exercise: GrammarExercise, patch: dict) -> None:
    raw = exercise.content
    updated = {**effective_content(exercise), **patch}
    exercise.answer_review_override = {
        'source_revision': _revision(exercise, raw),
        'grader_version': LAB_GRADER_VERSION,
        'patch': {k: updated[k] for k in (*ALIAS_FIELDS, 'correct_answer', 'correct_index')
                  if k in updated and updated[k] != raw.get(k)},
    }


def guided_override_for(exercise: GrammarExercise, content: dict) -> dict | None:
    """Return the decision for the same authored exercise under its new theory."""
    previous = exercise.content
    override = exercise.answer_review_override
    if (not isinstance(override, dict) or not isinstance(previous, dict)
            or not previous.get('guided_key') or override.get('grader_version') != LAB_GRADER_VERSION
            or override.get('source_revision') != _revision(exercise, previous)):
        return None
    display_fields = {'guided_revision', 'theory_help'}
    authored_before = {key: value for key, value in previous.items() if key not in display_fields}
    authored_after = {key: value for key, value in content.items() if key not in display_fields}
    if authored_before != authored_after:
        return None
    return {**override, 'source_revision': _revision(exercise, content)}


def rebase_guided_override(exercise: GrammarExercise, content: dict) -> None:
    override = guided_override_for(exercise, content)
    if override is not None and override != exercise.answer_review_override:
        exercise.answer_review_override = override
