"""Reconcile source-owned Grammar Lab exercises without deleting history."""
# ruff: noqa: RUF001 -- validation messages are displayed in Russian.
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.grammar_lab.content_catalog import content_digest
from app.grammar_lab.content_validator import validate_exercise_content
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.utils.db import db
from werkzeug.datastructures import FileStorage

JSON_SOURCE = 'json_import'
MODULE_SOURCE = 'module_import'
_GUIDED_FIELDS = {'guided_key', 'guided_rule_id', 'guided_revision', 'guided_retired'}
_EXERCISE_TYPES = {
    'fill_blank', 'multiple_choice', 'reorder', 'transformation',
    'error_correction', 'translation', 'true_false', 'matching',
}


@dataclass(frozen=True)
class ImportedExercise:
    exercise_type: str
    content: dict[str, Any]
    order: int
    difficulty: int = 1


@dataclass(frozen=True)
class ExerciseImportPlan:
    retained: int
    additions: list[ImportedExercise]
    retirements: list[GrammarExercise]
    metadata_updates: list[tuple[GrammarExercise, ImportedExercise]]


def prepare_exercise(
    exercise_type: object, content: object, *, source: str, order: int, difficulty: int = 1,
) -> ImportedExercise:
    if not isinstance(exercise_type, str) or exercise_type not in _EXERCISE_TYPES:
        raise ValueError(f'Неподдерживаемый тип упражнения: {exercise_type!r}')
    if not isinstance(content, dict):
        raise ValueError('Содержимое упражнения должно быть объектом JSON.')
    if _GUIDED_FIELDS.intersection(content):
        raise ValueError('Служебные поля guided нельзя задавать через этот импорт.')
    authored = {**content, 'source': source}
    json.dumps(authored, allow_nan=False)
    validate_exercise_content(exercise_type, authored)
    return ImportedExercise(exercise_type, authored, order, difficulty)


def lock_topics(topic_ids: Iterable[int]) -> dict[int, GrammarTopic]:
    ids = sorted(set(topic_ids))
    if not ids:
        return {}
    rows = (GrammarTopic.query.filter(GrammarTopic.id.in_(ids)).order_by(GrammarTopic.id)
            .with_for_update().populate_existing().all())
    if len(rows) != len(ids):
        raise ValueError('Темы изменились во время подготовки импорта. Повторите загрузку.')
    return {topic.id: topic for topic in rows}


def guided_topic(topic: GrammarTopic) -> bool:
    content = topic.content or {}
    return isinstance(content, dict) and bool(
        content.get('guided_catalog_digest') or content.get('guided_exercise_ids')
        or content.get('guided_content_version')
    )


def _identity(exercise_type: str, content: dict) -> str:
    # The source marker and the visibility flag are import metadata. The
    # caller scopes ownership separately. Authored lists retain their order.
    authored = {key: value for key, value in content.items() if key not in ('source', 'guided_retired')}
    return content_digest([exercise_type, authored])


def plan_replacement(
    topic: GrammarTopic | None, source: str, desired: Sequence[ImportedExercise],
) -> ExerciseImportPlan:
    """Plan after locking the topic. Use only rows with an unambiguous owner."""
    if not desired:
        return ExerciseImportPlan(0, [], [], [])
    owned: dict[str, list[GrammarExercise]] = defaultdict(list)
    unchanged_keys: set[str] = set()
    retired_keys: set[str] = set()
    if topic is not None:
        exercises = (GrammarExercise.query.filter_by(topic_id=topic.id).order_by(GrammarExercise.id)
                     .with_for_update().populate_existing().all())
        for exercise in exercises:
            content = exercise.content
            if not isinstance(content, dict) or (_GUIDED_FIELDS - {'guided_retired'}).intersection(content):
                continue
            owner = content.get('source')
            if owner != source and owner is not None:
                continue
            key = _identity(exercise.exercise_type, content)
            if content.get('guided_retired') is True:
                retired_keys.add(key)
            elif owner is None:
                if source == MODULE_SOURCE:
                    unchanged_keys.add(key)
            else:
                owned[key].append(exercise)

    incoming: dict[str, ImportedExercise] = {}
    for exercise in sorted(desired, key=lambda item: (item.order, item.difficulty)):
        incoming.setdefault(_identity(exercise.exercise_type, exercise.content), exercise)

    active_keys = set(owned) | unchanged_keys
    if any(key in retired_keys and key not in active_keys for key in incoming):
        raise ValueError(
            f'Тема «{topic.title}» содержит в загрузке ранее снятое упражнение. '
            'Импорт не вернул его в показ. Уберите его из набора и повторите загрузку.'
        )
    return ExerciseImportPlan(
        retained=sum(len(owned[key]) if key in owned else 1 for key in incoming if key in active_keys),
        additions=[exercise for key, exercise in incoming.items() if key not in active_keys],
        retirements=[exercise for key, rows in owned.items() if key not in incoming for exercise in rows],
        metadata_updates=[
            (current, incoming[key])
            for key, rows in owned.items() if key in incoming and source == JSON_SOURCE
            for current in rows
            if (current.order, current.difficulty) != (incoming[key].order, incoming[key].difficulty)
        ],
    )


def apply_replacement(topic: GrammarTopic, plan: ExerciseImportPlan) -> None:
    for exercise, desired in plan.metadata_updates:
        exercise.order = desired.order
        exercise.difficulty = desired.difficulty
    for exercise in plan.retirements:
        exercise.content = {**exercise.content, 'guided_retired': True}
    for exercise in plan.additions:
        db.session.add(GrammarExercise(
            topic_id=topic.id, exercise_type=exercise.exercise_type, content=exercise.content,
            order=exercise.order, difficulty=exercise.difficulty,
        ))


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f'Недопустимое число JSON: {value}')


def _file_exercises(file: FileStorage) -> tuple[list[str], list[ImportedExercise]]:
    filename = file.filename or ''
    if not filename.lower().endswith('.json'):
        raise ValueError('Допустимы только файлы JSON.')
    document = json.load(file, parse_constant=_invalid_json_constant)
    if not isinstance(document, dict):
        raise ValueError('Файл должен содержать объект JSON.')
    module = document.get('module_id')
    slug_part = document.get('grammar_topic_slug')
    if (type(module) not in (int, str) or not str(module).isascii() or not str(module).isdigit()
            or not isinstance(slug_part, str) or not slug_part.strip()):
        raise ValueError('Проверьте module_id и grammar_topic_slug.')
    level = document.get('level')
    slugs = [f'{level.lower()}-{module}'] if isinstance(level, str) and level else []
    match = re.search(r'grammar_extra_([a-z0-9]+)_(\d+)\.json$', filename, flags=re.IGNORECASE)
    if match:
        slugs.append(f'{match[1].lower()}-{match[2]}')
    sessions = document.get('sessions')
    if not isinstance(sessions, list):
        raise ValueError('Поле sessions должно быть списком.')
    exercises = []
    for session_number, entry in enumerate(sessions, 1):
        rows = entry.get('exercises') if isinstance(entry, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f'Сессия {session_number}: поле exercises должно быть списком.')
        for row_number, row in enumerate(rows, 1):
            try:
                if not isinstance(row, dict):
                    raise ValueError('Упражнение должно быть объектом JSON.')
                order = row.get('order', 0)
                if type(order) is not int or not 0 <= order <= 2**31 - 1:
                    raise ValueError('Порядок упражнения должен быть целым неотрицательным числом.')
                try:
                    difficulty = int(float(row.get('difficulty', 1)))
                except (OverflowError, TypeError, ValueError):
                    difficulty = 1
                exercises.append(prepare_exercise(
                    row.get('exercise_type', 'fill_blank'), row.get('content'),
                    source=JSON_SOURCE, order=order, difficulty=max(1, min(3, difficulty)),
                ))
            except ValueError as error:
                raise ValueError(f'Сессия {session_number}, упражнение {row_number}: {error}') from error
    if not exercises:
        raise ValueError('Файл не содержит упражнений.')
    return list(dict.fromkeys(slugs)), exercises


def prepare_json_batch(files: Sequence[FileStorage]) -> dict[int, tuple[str, list[ImportedExercise]]]:
    """Parse and validate every file before the route can write anything."""
    batch: dict[int, tuple[str, list[ImportedExercise]]] = {}
    for file in files:
        try:
            slugs, desired = _file_exercises(file)
            matches = GrammarTopic.query.filter(GrammarTopic.slug.in_(slugs)).all()
            if len(matches) != 1:
                raise ValueError(f'Не удалось однозначно определить тему ({", ".join(slugs) or "нет slug"}).')
            topic = matches[0]
            if guided_topic(topic):
                raise ValueError('Эта тема обновляется через guided-каталог.')
            batch.setdefault(topic.id, (topic.slug, []))[1].extend(desired)
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError(f'{file.filename}: {error}') from error
    return batch
