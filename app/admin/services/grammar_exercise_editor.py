"""Structured edits for ordinary Grammar Lab exercises."""

import re
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache

from app.curriculum.answer_review_edits import ALIAS_FIELDS, answer_aliases
from app.curriculum.blank_answers import blank_instruction, has_blank_gap
from app.grammar_lab.answer_review import (
    active_lab_override,
    effective_content,
    grade_row,
    lab_content_with_patch,
    rebased_lab_override,
)
from app.grammar_lab.content_catalog import content_digest
from app.grammar_lab.content_validator import validate_exercise_content
from app.grammar_lab.models import GrammarExercise
from app.utils.normalization import normalize_quiz_answer

WRITTEN_TYPES = frozenset(('translation', 'fill_blank'))
_COMMON = ('question', 'instruction', 'hint', 'explanation', 'correct_answer')
_FIELDS = {
    'reorder': (*_COMMON, 'words', 'alternatives'),
    'error_correction': (*_COMMON, 'sentence', 'error_word', 'correct_sentence', 'full_correct', *ALIAS_FIELDS),
    'translation': (*_COMMON, 'sentence', *ALIAS_FIELDS),
    'fill_blank': (*_COMMON, *ALIAS_FIELDS),
}
EDITABLE_TYPES = frozenset(_FIELDS)
_LIST_FIELDS = frozenset(('words', *ALIAS_FIELDS))
_PATCH_FIELDS = frozenset(('correct_answer', *ALIAS_FIELDS))
_DIRECTIONS = {'ru-en': ('ru', 'en'), 'en-ru': ('en', 'ru')}
_TRANSLATION_PREFIX = re.compile(r'^Переведите на (английский|русский):\s*', re.I)


@dataclass(frozen=True)
class ExerciseEdit:
    authored: dict
    override: dict | None
    effective: dict
    difficulty: int | None
    order: int | None
    needs_confirmation: bool


def editor_revision(exercise: GrammarExercise) -> str:
    return content_digest([
        exercise.id, exercise.topic_id, exercise.exercise_type, exercise.content,
        exercise.answer_review_override, exercise.order, exercise.difficulty,
    ])


def _display(value: object) -> str:
    if isinstance(value, list):
        value = '\n'.join(item for item in value if isinstance(item, str))
    return value.replace('\r\n', '\n').replace('\r', '\n').strip() if isinstance(value, str) else ''


def fields_for(exercise: GrammarExercise) -> dict[str, str]:
    current = effective_content(exercise)
    fields = {field: _display(current.get(field)) for field in _FIELDS[exercise.exercise_type]}
    if exercise.exercise_type in WRITTEN_TYPES:
        for field in ALIAS_FIELDS[1:]:
            if not fields[field]:
                del fields[field]
    if exercise.exercise_type == 'translation':
        fields['direction'] = _translation_direction(current)
    return fields


def _translation_direction(row: dict) -> str:
    target = str(row.get('target_lang') or 'en').lower()
    return 'en-ru' if target in ('ru', 'rus', 'russian') else 'ru-en'


def _translation_phrase(row: dict) -> str:
    return _TRANSLATION_PREFIX.sub('', row.get('sentence') or row.get('question') or '').strip()


def written_prompt(kind: str, row: dict) -> tuple[str, str, str] | None:
    """Show the wording used by the ordinary web practice."""
    question = row.get('question') or ''
    if kind == 'fill_blank':
        instruction = blank_instruction(row, kind=kind, canonical=row.get('correct_answer'))
        return (instruction if question else '', question or instruction or 'Заполните пропуск:', 'en')
    if kind == 'translation':
        phrase = _translation_phrase(row)
        source, target = _DIRECTIONS[_translation_direction(row)]
        default = 'Переведите на русский:' if target == 'ru' else 'Переведите на английский:'
        label = row.get('instruction') or (question if question.strip() != phrase else '') or default
        return label, phrase, source
    return None


def _tiles(row: dict) -> Counter:
    words = row.get('words')
    return Counter(word for word in words if isinstance(word, str)) if isinstance(words, list) else Counter()


def accepted_answers(exercise: GrammarExercise, row: dict) -> list[str]:
    """List explicit configured answers which the real grader accepts."""
    configured = []
    for key in ('correct_answer', 'correct_sentence', 'full_correct'):
        value = row.get(key)
        configured.extend(value if isinstance(value, list) else [value])
    configured.extend(answer_aliases(row))
    candidates = dict.fromkeys(value for value in configured if isinstance(value, str) and value)
    return [value for value in candidates if grade_row(exercise, row, value)['is_correct']]


def _tile_order(words: list[str], correct: str) -> list[int] | None:
    """Prove reachability with repeated tiles and tiles that contain a phrase."""
    positions: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index, word in enumerate(words):
        positions[tuple(normalize_quiz_answer(word).split())].append(index)
    visible = tuple(tile for tile in positions if tile)
    normalized = tuple(normalize_quiz_answer(correct).split())

    @cache
    def match(offset: int, counts: tuple[int, ...]) -> tuple[int, ...] | None:
        if offset == len(normalized):
            return () if not any(counts) else None
        if match.cache_info().misses > 4096:
            raise ValueError('Порядок нельзя однозначно сверить. Упростите границы плиток.')
        for index, tile in enumerate(visible):
            if counts[index] and normalized[offset:offset + len(tile)] == tile:
                remaining = (*counts[:index], counts[index] - 1, *counts[index + 1:])
                tail = match(offset + len(tile), remaining)
                if tail is not None:
                    position = positions[tile][counts[index] - 1]
                    return (position, *tail)
        return None

    match_indices = match(0, tuple(len(positions[tile]) for tile in visible))
    return [*match_indices, *positions.get((), ())] if match_indices is not None else None


def _field_value(key: str, text: str, previous: object) -> object:
    limit = 8000 if key in _LIST_FIELDS else 4000 if key == 'explanation' else 500
    if (len(text) > limit or '<' in text or '>' in text
            or any(ord(char) < 32 and char != '\n' for char in text) or '\x7f' in text):
        raise ValueError('Проверьте длину и символы в полях упражнения.')
    if key in _LIST_FIELDS or (key == 'correct_sentence' and (isinstance(previous, list) or '\n' in text)):
        values = [line.strip() for line in text.splitlines() if line.strip()]
        if len(values) > 40 or any(len(value) > 500 for value in values):
            raise ValueError('Укажите до 40 строк, не более 500 символов в каждой.')
        return values
    return text


def _validate(exercise: GrammarExercise, row: dict) -> None:
    validate_exercise_content(exercise.exercise_type, row)
    if exercise.exercise_type in WRITTEN_TYPES:
        key = row['correct_answer']
        keys = key if isinstance(key, list) else [key]
        if not all(isinstance(value, str) and grade_row(exercise, row, value)['is_correct'] for value in keys):
            raise ValueError('Укажите текстовый ключ, который принимает проверка.')
        if exercise.exercise_type == 'translation' and not _translation_phrase(row):
            raise ValueError('Укажите исходную фразу для перевода.')
        if exercise.exercise_type == 'fill_blank' and not has_blank_gap(row.get('question')):
            raise ValueError('Обозначьте пропуск двумя или более подчёркиваниями.')
        return
    if exercise.exercise_type == 'error_correction':
        if not (row.get('sentence') or row.get('question')) or not accepted_answers(exercise, row):
            raise ValueError('Нужны ошибочная фраза и хотя бы один ответ, который принимает проверка.')
        return
    words, key = row.get('words'), row.get('correct_answer')
    if (not isinstance(words, list) or not 2 <= len(words) <= 40
            or not all(isinstance(word, str) and word.strip() and len(word) <= 120 for word in words)):
        raise ValueError('Введите от 2 до 40 непустых плиток, по одной на строку.')
    for value in [key, *(row.get('alternatives') or [])]:
        if not isinstance(value, str):
            raise ValueError('Ключ и варианты должны содержать текст.')
        order = _tile_order(words, value)
        if order is None or not grade_row(exercise, row, order)['is_correct']:
            raise ValueError(f'Ответ «{value}» не собирается из всех показанных плиток.')


def plan_edit(
    exercise: GrammarExercise, submitted: Mapping[str, str], difficulty: int | None, order: int | None,
) -> ExerciseEdit | None:
    valid_difficulty = exercise.difficulty is None if difficulty is None else difficulty in (1, 2, 3)
    valid_order = exercise.order is None if order is None else 0 <= order <= 2_147_483_647
    if not valid_difficulty or not valid_order:
        raise ValueError('Порядок должен быть неотрицательным, а сложность от 1 до 3.')  # noqa: RUF001 -- Russian form message.
    before = effective_content(exercise)
    active = active_lab_override(exercise)
    authored = exercise.content.copy()
    patch = {}
    for key, value in submitted.items():
        if key == 'direction':
            if value not in _DIRECTIONS:
                raise ValueError('Выберите направление перевода.')
            if value != _translation_direction(before):
                authored['source_lang'], authored['target_lang'] = _DIRECTIONS[value]
            continue
        if value == _display(before.get(key)):
            continue
        key_list = key == 'correct_answer' and exercise.exercise_type in WRITTEN_TYPES and (
            isinstance(before.get(key), list) or '\n' in value
        )
        new = _field_value('alternatives' if key_list else key, value, before.get(key))
        if active and key in _PATCH_FIELDS:
            patch[key] = new
        elif new or key == 'correct_answer':
            authored[key] = new
        else:
            authored.pop(key, None)
    override = rebased_lab_override(exercise, authored, patch)
    next_active = override if active else active_lab_override(exercise, authored)
    after = lab_content_with_patch(authored, next_active['patch']) if next_active else authored
    if (authored == exercise.content and override == exercise.answer_review_override
            and difficulty == exercise.difficulty and order == exercise.order):
        return None
    _validate(exercise, after)
    relevant = set(_FIELDS[exercise.exercise_type]) - {'hint', 'explanation', 'words'}
    if exercise.exercise_type == 'translation':
        relevant.update(('source_lang', 'target_lang'))
    if exercise.exercise_type == 'reorder':
        relevant -= {'correct_answer', 'alternatives'}
        before_answers, after_answers = (
            {normalize_quiz_answer(answer) for answer in accepted_answers(exercise, row)} for row in (before, after)
        )
        answer_change = before_answers != after_answers
    else:
        answer_change = False
    semantic = answer_change or _tiles(before) != _tiles(after) or any(before.get(key) != after.get(key) for key in relevant)
    needs_confirmation = bool((active and semantic) or (not active and next_active))
    return ExerciseEdit(authored, override, after, difficulty, order, needs_confirmation)
