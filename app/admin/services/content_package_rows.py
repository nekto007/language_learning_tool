"""Compare-and-set a small set of question rows in installed curriculum lessons."""
# ruff: noqa: RUF001 -- validation errors are displayed in Russian.

import json
from collections import Counter
from copy import deepcopy

from marshmallow import ValidationError

from app.admin.services.guided_lesson_import import is_published_guided_lesson
from app.curriculum.answer_disputes import AnswerDispute
from app.curriculum.grading import _quiz_option_index, normalize_quiz_answer
from app.curriculum.models import CEFRLevel, Lessons, Module
from app.curriculum.validators import LessonContentValidator
from app.grammar_lab.content_catalog import content_digest

ROW_PACKAGE = 'lesson_rows_v1'
_QUIZZES = {
    'dialogue_completion_quiz': {'options'},
    'translation_quiz': {'question', 'correct', 'acceptable_answers', 'explanation'},
    'ordering_quiz': {'acceptable_answers'},
    'sentence_completion': {'acceptable_answers'},
}
_AUDIO_FIELDS = {'audio', 'audio_url', 'audio_clip_url'}
_TEXT_FIELDS = {'type', 'question', 'question_ru', 'instruction', 'options', 'correct', 'explanation',
                'transcript', 'audio_text', 'translation', 'audio_translation', 'prompt_role'}
_WRITING_FIELDS = frozenset({'prompt', 'prompt_ru', 'mode', 'checklist', 'target_phrases', 'template',
                            'example_response', 'hint_words', 'hint', 'hints'})


class QuestionAnchorConflict(ValueError):
    """The exact source row cannot be uniquely confirmed at its archive position."""

    def __init__(
        self, reason: str, path: tuple[str | int, ...], *, fields: set[str] | None = None,
        moved_index: int | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.path = path
        self.fields = fields or set()
        self.moved_index = moved_index
        self.target: dict = {}


def writing_guard(content: dict) -> str:
    """Bind an editorial change to the current writing directions and rubric."""
    return content_digest({key: value for key, value in content.items()
                           if key in _WRITING_FIELDS or key.startswith('min_')})


def _ordered_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False)


def _display_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


def _slots(content: dict, kind: str) -> dict[tuple[str | int, ...], list]:
    """Locate only the list that is actually projected for this lesson."""
    if kind == 'sentence_completion':
        return {('items',): content.get('items', [])}
    if kind == 'final_test':
        field = 'test_sections' if content.get('test_sections') else 'sections'
        if sections := content.get(field):
            result = {}
            for index, section in enumerate(sections):
                name = 'exercises' if section.get('exercises') else 'questions'
                if section.get(name):
                    result[(field, index, name)] = section[name]
            return result
    name = 'questions' if content.get('questions') else 'exercises'
    return {(name,): content.get(name, [])}


def _check_row(kind: str, previous: dict, updated: dict, fields: set[str]) -> None:
    if kind in _QUIZZES:
        allowed = _QUIZZES[kind]
    elif previous.get('type') == 'listening_choice':
        if updated.get('type') == 'listening_choice':
            allowed = _AUDIO_FIELDS
            if not any(isinstance(updated.get(key), str) and updated[key].strip() for key in _AUDIO_FIELDS):
                raise ValueError('Заданию на аудирование нужна ссылка на запись.')
        elif updated.get('type') == 'multiple_choice':
            allowed = _AUDIO_FIELDS | _TEXT_FIELDS
            if (not updated.get('question') or not updated.get('instruction')
                    or any(updated.get(key) for key in _AUDIO_FIELDS)):
                raise ValueError('Для замены аудиовопроса нужны видимое условие и текстовая инструкция.')
        else:
            raise ValueError('Допустима замена аудиовопроса на текстовый вопрос с выбором.')
    else:
        raise ValueError('Точечная замена в этом типе урока доступна только для вопроса на аудирование.')
    if not fields or fields - allowed:
        raise ValueError('Правка содержит пустой или неподдерживаемый набор полей.')
    if kind in ('dialogue_completion_quiz', 'listening_quiz', 'final_test'):
        options = updated.get('options')
        keys = ('answer', 'correct_answer', 'correct', 'correct_index')
        field = next((key for key in keys if key in updated), '')
        if (not isinstance(options, list) or not 2 <= len(options) <= 6
                or any(not isinstance(option, str) or not option.strip() for option in options)
                or _quiz_option_index(options, updated.get(field), prefer_literal=field != 'correct_index') < 0):
            raise ValueError('Укажите варианты и действующий ключ ответа.')
    if 'acceptable_answers' in fields:
        candidates = updated.get('acceptable_answers')
        if (not isinstance(candidates, list) or not candidates
                or any(not isinstance(value, str) or not value.strip() for value in candidates)):
            raise ValueError('Проверьте текстовые варианты ответа.')
        if kind == 'ordering_quiz':
            words = Counter(normalize_quiz_answer(word) for word in updated.get('words', []))
            for answer in candidates:
                if Counter(normalize_quiz_answer(answer).split()) != words:
                    raise ValueError('Вариант порядка должен собираться из исходных плиток.')


def _different_fields(before: dict, after: dict) -> set[str]:
    return {key for key in before.keys() | after.keys()
            if key not in before or key not in after or _ordered_json(before[key]) != _ordered_json(after[key])}


def _plan_changes(lesson: Lessons, changes: list) -> tuple[dict, list[dict]]:
    content = deepcopy(lesson.content)
    slots = _slots(content, lesson.type)
    summaries: list[dict] = []
    used = set()
    for change in changes:
        if not isinstance(change, dict) or change.keys() != {'path', 'before', 'after'}:
            raise ValueError('Укажите путь, исходное задание и новую версию.')
        path, before, after = (change[key] for key in ('path', 'before', 'after'))
        if lesson.type == 'writing_prompt':
            if not isinstance(path, list) or len(path) != 1 or not isinstance(path[0], str):
                raise ValueError('Для письменного задания укажите одно поле.')
            field = path[0]
            if field == 'min_sentences':
                valid = type(before) is int and type(after) is int and 1 <= after < before
            elif field in ('hint_words', 'target_phrases'):
                valid = (content.get('mode') == 'structured' and isinstance(before, list) and isinstance(after, list)
                         and bool(after) and all(isinstance(item, str) and item.strip() for item in after))
            else:
                valid = (field in ('prompt_ru', 'example_response', 'template') and isinstance(before, str)
                         and isinstance(after, str) and bool(after.strip()))
            if (not valid or (field,) in used or before == after
                    or _ordered_json(content.get(field)) != _ordered_json(before)):
                raise ValueError(f'Проверьте исходное значение и замену поля {field}.')
            summaries.append({'path': field, 'before': before if isinstance(before, str) else _display_json(before),
                              'after': after if isinstance(after, str) else _display_json(after)})
            content[field] = after
            used.add((field,))
            continue
        if (not isinstance(path, list) or len(path) not in (2, 4)
                or any(type(key) not in (str, int) for key in path)
                or type(path[-1]) is not int or not isinstance(before, dict) or not isinstance(after, dict)):
            raise ValueError('Проверьте путь и объекты задания.')
        address = tuple(path)
        rows = slots.get(address[:-1])
        index = address[-1]
        if address in used or index < 0:
            raise ValueError('Путь к заданию отсутствует или повторяется.')
        if rows is None:
            raise QuestionAnchorConflict('missing', address)
        anchor = _ordered_json(before)
        matches = [position for position, row in enumerate(rows) if _ordered_json(row) == anchor]
        if len(matches) > 1:
            raise QuestionAnchorConflict('ambiguous', address)
        if matches and matches[0] != index:
            raise QuestionAnchorConflict('moved', address, moved_index=matches[0])
        if index >= len(rows):
            raise QuestionAnchorConflict('missing', address)
        if not matches:
            current = rows[index]
            raise QuestionAnchorConflict('changed', address, fields=_different_fields(before, current)
                                         if isinstance(current, dict) else set())
        fields = _different_fields(before, after)
        _check_row(lesson.type, before, after, fields)
        seen_fields = sorted(fields)
        summaries.append({'path': ' / '.join(str(value + 1 if type(value) is int else value) for value in address),
                          'before': _display_json({key: before[key] for key in seen_fields if key in before}),
                          'after': _display_json({key: after[key] for key in seen_fields if key in after})})
        rows[index] = deepcopy(after)
        used.add(address)
    try:
        LessonContentValidator.validate(lesson.type, content)
    except ValidationError as error:
        raise ValueError(f'Урок не прошёл штатную проверку: {error.messages}') from error
    if used.intersection({('min_sentences',), ('example_response',)}):
        from app.api.native_content import _writing_requirements
        from app.curriculum.routes.lessons import _DEFAULT_WRITING_CHECKLIST

        result = _writing_requirements(lesson, content, {
            'text': content.get('example_response') or '',
            'checked': content.get('checklist') or _DEFAULT_WRITING_CHECKLIST,
        })
        if not result['completed']:
            raise ValueError('Образец не выполняет условия завершения письменного задания.')
    return content, summaries


def plan_row_package(entries: list[dict], *, lock: bool = False) -> tuple[list[dict], list[tuple[Lessons, dict]]]:
    targets = {}
    names = set()
    for entry in entries:
        doc, name = entry['data'], entry['name']
        fields = {'kind', 'external_key', 'level', 'module_number', 'lesson_type', 'changes'}
        if doc.get('lesson_type') == 'writing_prompt':
            fields.add('writing_guard')
        if doc.keys() != fields:
            raise ValueError('Точечный ZIP должен содержать только документы правок заданий.')
        level, number, key, kind, changes = (
            doc[field] for field in ('level', 'module_number', 'external_key', 'lesson_type', 'changes')
        )
        if (doc['kind'] != ROW_PACKAGE or not isinstance(key, str) or not key or key != key.strip()
                or not isinstance(level, str) or type(number) is not int or number <= 0
                or not isinstance(kind, str) or kind not in _QUIZZES.keys() | {'listening_quiz', 'final_test', 'writing_prompt'}
                or not isinstance(changes, list) or not 1 <= len(changes) <= 40 or key in targets or name in names):
            raise ValueError('Проверьте область урока, уникальность ключа и число правок.')
        targets[key] = (level, number, kind, changes, name, doc.get('writing_guard'))
        names.add(name)
    planned = []
    summaries = []
    for key, (level, number, kind, changes, name, guard) in sorted(
        targets.items(), key=lambda item: (*item[1][:2], item[0]),
    ):
        modules = Module.query.join(CEFRLevel).filter(CEFRLevel.code == level, Module.number == number)
        module = (modules.with_for_update(of=Module) if lock else modules).populate_existing().one_or_none()
        if module is None:
            raise ValueError(f'Модуль {level} №{number} не найден.')
        query = Lessons.query.filter(Lessons.content['external_key'].as_string() == key).populate_existing()
        lessons = (query.with_for_update() if lock else query).order_by(Lessons.id).limit(2).all()
        if (len(lessons) != 1 or lessons[0].module_id != module.id or lessons[0].type != kind
                or is_published_guided_lesson(lessons[0])):
            raise ValueError(f'Ключ «{key}» должен относиться к одному обычному уроку указанного модуля и типа.')
        lesson = lessons[0]
        try:
            if kind == 'writing_prompt' and guard != writing_guard(lesson.content):
                raise ValueError('Условия письменного задания или образец изменились. Сверьте текущую версию.')
            # Legacy approvals may bind the entire course document revision,
            # including when the corrected question is outside this patch.
            if AnswerDispute.query.filter_by(lesson_id=lesson.id, status='applied').first() is not None:
                raise ValueError('Есть применённое решение спора. Сверьте его перед точечной правкой.')
            content, changes_summary = _plan_changes(lesson, changes)
        except QuestionAnchorConflict as error:
            error.target = {'file': name, 'level': level, 'module': number, 'lesson': lesson.title,
                            'lesson_id': lesson.id, 'lesson_number': lesson.number}
            raise
        except ValueError as error:
            raise ValueError(f'{level} М{number} · {lesson.title}: {error}') from error
        summaries.append({'name': name, 'title': f'{level} · Модуль {number} · {lesson.title}', 'kind': 'lesson_rows',
                          'count': len(changes), 'operation': 'update', 'preserved_guided': [],
                          'fingerprint': content_digest([module.id, lesson.id, kind, changes, guard]),
                          'changes': changes_summary})
        planned.append((lesson, content))
    return summaries, planned
