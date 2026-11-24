"""Validate and publish authored curriculum data within the administrator's transaction."""
# ruff: noqa: RUF001 -- validation errors are shown to Russian-speaking administrators.
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

from marshmallow import ValidationError
from sqlalchemy import text

from app.admin.services.curriculum_import_service import ALLOWED_CEFR_LEVELS, CurriculumImportService
from app.admin.services.guided_lesson_import import is_published_guided_lesson, preserved_guided_lessons
from app.api.native_content import CHOICE, FILL_BLANKS, TEXT, _prompt
from app.curriculum.grading import _pair_left, _pair_right, _quiz_option_index, _strict_bool
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.curriculum.validators import LessonContentValidator, QuizQuestionSchema
from app.utils.db import db
from app.utils.db_utils import chunk_ids


def _string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _objects(value: object, label: str) -> list[dict]:
    if not isinstance(value, list) or not value or not all(isinstance(row, dict) for row in value):
        raise ValueError(f'{label} — нужен непустой список объектов.')
    return value


def _schema(kind: str, data: dict) -> None:
    try:
        LessonContentValidator.validate(kind, data)
    except ValidationError as error:
        raise ValueError(f'Проверьте содержимое урока ({kind}): {error.messages}') from error


def _is_gradable(row: dict) -> bool:
    kind = row.get('type', 'multiple_choice')
    if not isinstance(kind, str):
        return False
    field = next((k for k in ('answer', 'correct_answer', 'correct', 'correct_index', 'correct_sentence') if k in row), '')
    answer = row.get(field)
    if kind not in ('matching', 'ordering', 'reorder') and not _prompt(row):
        return False
    if kind in CHOICE or (kind in FILL_BLANKS and row.get('options')):
        options = row.get('options')
        return (isinstance(options, list) and len(options) >= 2 and all(map(_string, options))
                and _quiz_option_index(options, answer, prefer_literal=field != 'correct_index') >= 0)
    if kind == 'true_false':
        return _strict_bool(answer) is not None
    if kind == 'matching':
        pairs = row.get('pairs')
        return (isinstance(pairs, list) and bool(pairs)
                and all(isinstance(pair, dict) and _pair_left(pair).strip() and _pair_right(pair).strip()
                        for pair in pairs))
    text_key = _string(answer) or (isinstance(answer, list) and bool(answer) and all(map(_string, answer)))
    if kind in ('ordering', 'reorder'):
        words = row.get('words')
        return isinstance(words, list) and bool(words) and all(map(_string, words)) and text_key
    return kind in TEXT and bool(kind) and text_key


def _final_count(data: dict) -> int:
    _schema('final_test', data)
    for key in ('passing_score', 'pass_score', 'total_points', 'total_questions', 'time_limit', 'xp_reward'):
        if key in data and (type(data[key]) is not int or data[key] < 0):
            raise ValueError(f'Поле {key} должно содержать целое неотрицательное число.')
    sections = data.get('test_sections') or data.get('sections')
    if sections:
        groups = [section.get('exercises') or section.get('questions')
                  for section in _objects(sections, 'Разделы теста')]
    else:
        if data.get('questions') and 'exercises' in data and data['exercises'] != data['questions']:
            raise ValueError('В плоском тесте укажите один список заданий: exercises или questions.')
        groups = [data.get('exercises') or data.get('questions')]
    count = 0
    for group in groups:
        for row in _objects(group, 'Задания теста'):
            count += 1
            if not sections:
                try:
                    QuizQuestionSchema().load(row)
                except ValidationError as error:
                    raise ValueError(f'Проверьте поля задания {count}: {error.messages}') from error
            if not _is_gradable(row):
                raise ValueError(f'Задание {count} итогового теста — проверьте тип, варианты и ключ ответа.')
    return count


@dataclass
class _Target:
    name: str
    data: dict
    level: str
    number: int
    kind: str
    title: str
    count: int
    lesson_key: str = ''
    module_keys: dict[str, str] | None = None


def _module_target(name: str, data: dict) -> _Target:
    source = data['module'] if isinstance(data['module'], dict) else data
    lessons = _objects(source.get('lessons'), 'Уроки модуля')
    if not _string(source.get('level')) or source['level'] not in ALLOWED_CEFR_LEVELS:
        raise ValueError('Проверьте уровень CEFR модуля.')
    if not _string(source.get('title')) or len(source['title']) > 200:
        raise ValueError('Укажите название модуля длиной до 200 символов.')
    if 'prerequisites' in source and not isinstance(source['prerequisites'], list):
        raise ValueError('Предварительные условия модуля должны быть списком.')
    for row in lessons:
        if not _string(row.get('lesson_type') or row.get('type')):
            raise ValueError('Укажите тип каждого урока.')
        if any(type(row[k]) is not int or row[k] <= 0 for k in ('id', 'order', 'lesson_number') if k in row):
            raise ValueError('Номер и порядок урока должны быть положительными целыми числами.')
    info = CurriculumImportService.preview_import(data)
    if type(info['module_number']) is not int or not 0 < info['module_number'] < 2**31:
        raise ValueError('Номер модуля должен быть положительным целым числом.')
    numbers, keys = set(), {}
    for row, item in zip(lessons, info['lessons'], strict=True):
        n, kind = item['number'], item['type']
        if type(n) is not int or not 0 < n < 10000 or n in numbers:
            raise ValueError('Для каждого урока укажите уникальный номер от 1 до 9999.')
        numbers.add(n)
        if not _string(item['title']) or len(item['title']) > 200:
            raise ValueError(f'Укажите название урока №{n} длиной до 200 символов.')
        content = row.get('content', row)
        if not isinstance(content, dict) or not content:
            raise ValueError(f'Урок №{n} — ожидается содержимое урока.')
        key = content.get('external_key')
        if key is not None and (not _string(key) or key != key.strip() or key in keys):
            raise ValueError(f'Проверьте внешний ключ урока №{n}.')
        if key:
            keys[key] = kind
        if kind == 'final_test':
            _final_count(content)
        else:
            _schema(kind, content)
    return _Target(name, data, info['level'], info['module_number'], 'module', info['module_title'],
                   len(lessons), module_keys=keys)


def _final_lesson(key: str, lock: bool = False) -> Lessons:
    query = Lessons.query.filter(Lessons.content['external_key'].as_string() == key).populate_existing()
    if lock:
        query = query.with_for_update()
    candidates = query.order_by(Lessons.id).limit(2).all()
    if len(candidates) != 1 or candidates[0].type != 'final_test':
        raise ValueError('Внешний ключ должен указывать ровно на один существующий итоговый тест.')
    return candidates[0]


def _check_final_key_owners(targets: list[_Target]) -> None:
    """The standalone importer addresses final tests by key across the whole course."""
    scopes: dict[str, set[tuple[str, int]]] = {}
    final_keys = set()
    for target in targets:
        for key, kind in (target.module_keys or {}).items():
            scopes.setdefault(key, set()).add((target.level, target.number))
            if kind == 'final_test':
                final_keys.add(key)
    if any(len(scopes[key]) > 1 for key in final_keys):
        raise ValueError('Файлы разных модулей содержат один внешний ключ итогового теста.')

    external_key = Lessons.content['external_key'].as_string()
    for keys in chunk_ids(list(scopes)):
        matches = (db.session.query(external_key, Lessons.type, CEFRLevel.code, Module.number)
                   .select_from(Lessons).join(Module, Module.id == Lessons.module_id)
                   .join(CEFRLevel, CEFRLevel.id == Module.level_id).filter(external_key.in_(keys)))
        for key, kind, level, number in matches:
            if (kind == 'final_test' or key in final_keys) and scopes[key] != {(level, number)}:
                raise ValueError('Внешний ключ итогового теста уже используется в другом модуле.')


def _targets(entries: list[dict]) -> list[_Target]:
    targets = []
    modules, tests, names = set(), set(), set()
    for entry in _objects(entries, 'Файлы пакета'):
        name, data = entry.get('name'), entry.get('data')
        if not _string(name) or name in names or not isinstance(data, dict):
            raise ValueError('Проверьте имена и содержимое файлов в пакете.')
        names.add(name)
        if 'module' in data:
            target = _module_target(name, data)
            scope = (target.level, target.number)
            if scope in modules:
                raise ValueError('Два файла описывают один и тот же модуль.')
            modules.add(scope)
        else:
            key = data.get('external_key')
            if not _string(key) or key != key.strip() or key in tests:
                raise ValueError('Для итогового теста нужен уникальный внешний ключ.')
            count = _final_count(data)
            lesson = _final_lesson(key)
            module = lesson.module
            target = _Target(name, data, module.level.code, module.number, 'final_test', lesson.title, count, key)
            tests.add(key)
        targets.append(target)
    if any(t.lesson_key and (t.level, t.number) in modules for t in targets):
        raise ValueError('Модуль и его отдельный итоговый тест нельзя публиковать в одном пакете.')
    _check_final_key_owners(targets)
    return targets


def _lesson_state(lesson: Lessons) -> list:
    return [lesson.id, lesson.module_id, lesson.number, lesson.order, lesson.title, lesson.description,
            lesson.type, lesson.collection_id, lesson.grammar_topic_id, lesson.content_version, lesson.content]


def _module_state(target: _Target, lock: bool) -> tuple[list | None, list[dict]]:
    query = Module.query.join(CEFRLevel).filter(CEFRLevel.code == target.level, Module.number == target.number)
    module = (query.with_for_update(of=Module) if lock else query).populate_existing().one_or_none()
    if module is None:
        return None, []
    query = Lessons.query.filter_by(module_id=module.id).order_by(Lessons.id)
    lessons = (query.with_for_update() if lock else query).populate_existing().all()
    # An authored key beats position. Ambiguous legacy title matches or two
    # source lessons resolving to the same record would steal learner history.
    source = target.data['module'] if isinstance(target.data['module'], dict) else target.data
    preserved = preserved_guided_lessons(lessons, source['lessons'])
    ordinary = [lesson for lesson in lessons if not is_published_guided_lesson(lesson)]
    by_number = {lesson.number: lesson for lesson in ordinary}
    by_id = {lesson.id: lesson for lesson in ordinary}
    by_key = {}
    by_title = {}
    seen_keys = set()
    for lesson in lessons:
        key = lesson.content.get('external_key') if isinstance(lesson.content, dict) else None
        if key:
            if not _string(key) or key in seen_keys:
                raise ValueError('В модуле неоднозначные внешние ключи уроков.')
            seen_keys.add(key)
        if is_published_guided_lesson(lesson):
            continue
        if key:
            by_key[key] = lesson
        by_title.setdefault((lesson.type, lesson.title.strip().lower()), []).append(lesson)
    used = set()
    for index, row in enumerate(source['lessons']):
        if index in preserved:
            used.add(preserved[index].id)
            continue
        key = (row.get('content') or {}).get('external_key')
        kind = row.get('lesson_type') or row.get('type')
        title = ('card' if kind == 'flashcards' else kind, row['title'].strip().lower())
        n = row.get('lesson_number') or row.get('order') or row.get('id')
        matched = by_key.get(key)
        if matched and matched.type != title[0]:
            raise ValueError('Внешний ключ относится к уроку другого типа.')
        if matched is None:
            matches = by_title.get(title, [])
            if len(matches) > 1:
                raise ValueError('У нескольких уроков одинаковые тип и название. Уточните внешние ключи.')
            fallback = (matches[0] if matches else by_number.get(n)) or by_id.get(row.get('id'))
            if fallback:
                old_key = (fallback.content or {}).get('external_key') if isinstance(fallback.content, dict) else None
                if old_key or (fallback.type, fallback.title.strip().lower()) != title:
                    raise ValueError('Номер или название занятия пересекается с другим уроком. Уточните внешние ключи.')
                matched = fallback
        if matched is not None:
            if matched.id in used:
                raise ValueError('Два исходных занятия соответствуют одному уроку в базе.')
            used.add(matched.id)
    protected_numbers = {lesson.number for lesson in lessons if lesson.id not in used}
    numbers = {row.get('lesson_number') or row.get('order') or row.get('id') for row in source['lessons']}
    if protected_numbers & numbers:
        raise ValueError('Один из номеров занят уроком, который отсутствует в пакете.')
    state = [module.id, module.title, module.description, module.raw_content, module.input_mode,
             module.prerequisites, [_lesson_state(lesson) for lesson in lessons]]
    guided = [{'number': lesson.number, 'title': lesson.title}
              for lesson in sorted(lessons, key=lambda lesson: lesson.number) if is_published_guided_lesson(lesson)]
    return state, guided


def _inspect(targets: list[_Target], lock: bool) -> list[dict]:
    rows = {}
    for target in sorted(targets, key=lambda t: (t.level, t.number, t.lesson_key)):
        guided = []
        if target.lesson_key:
            lesson = _final_lesson(target.lesson_key, lock=lock)
            if lesson.module.number != target.number or lesson.module.level.code != target.level:
                raise ValueError('Итоговый тест перемещён. Повторите просмотр пакета.')
            state = _lesson_state(lesson)
        else:
            state, guided = _module_state(target, lock)
        digest = hashlib.sha256(json.dumps([target.data, state], sort_keys=True, separators=(',', ':'),
                                           ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        title = f'{target.level} · Модуль {target.number} · {target.title}'
        rows[target.name] = {'name': target.name, 'title': title, 'kind': target.kind,
                             'count': target.count, 'operation': 'create' if state is None else 'update',
                             'fingerprint': digest, 'preserved_guided': guided}
    return [rows[target.name] for target in targets]


def preview_package(entries: list[dict]) -> list[dict]:
    """Read the exact current publication targets. Nothing is written."""
    return _inspect(_targets(entries), lock=False)


def apply_package(entries: list[dict], preview: list[dict]) -> None:
    """Flush every publication together. The caller commits with its audit row."""
    with db.session.begin_nested():
        if db.session.get_bind().dialect.name == 'postgresql':
            # New modules and new globally addressed final keys have no row to
            # lock. Compare their owners only after the prior publisher commits.
            db.session.execute(text("SELECT pg_advisory_xact_lock(1819046979, 1)"))
        targets = _targets(entries)
        if _inspect(targets, lock=True) != preview:
            raise ValueError('Содержимое изменилось после просмотра. Загрузите пакет и проверьте изменения ещё раз.')
        for target in sorted(targets, key=lambda t: (t.level, t.number, t.lesson_key)):
            if target.kind == 'module':
                CurriculumImportService.import_curriculum_data(deepcopy(target.data), commit=False)
            else:
                lesson = _final_lesson(target.lesson_key, lock=True)
                metadata = {k: v for k, v in lesson.content.items()
                            if k not in ('test_sections', 'sections', 'questions', 'exercises')}
                content = {**metadata, **target.data}
                if lesson.content != content:
                    lesson.content = content
        db.session.flush()
