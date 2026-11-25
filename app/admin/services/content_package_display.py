"""Build display data from the staged package without changing its publication summary."""
# ruff: noqa: RUF001 -- labels in the package editor are in Russian.

import json
from collections import Counter
from collections.abc import Iterable

_FIELDS = {
    'acceptable_answers': 'Допустимые ответы',
    'audio': 'Аудиозапись',
    'audio_clip_url': 'Аудиозапись',
    'audio_text': 'Текст записи',
    'audio_translation': 'Перевод записи',
    'audio_url': 'Аудиозапись',
    'correct': 'Правильный ответ',
    'example_response': 'Пример ответа',
    'explanation': 'Объяснение',
    'hint_words': 'Подсказки',
    'instruction': 'Инструкция',
    'min_sentences': 'Минимум предложений',
    'options': 'Варианты ответа',
    'prompt_role': 'Роль текста задания',
    'prompt_ru': 'Задание на русском',
    'question': 'Вопрос',
    'question_ru': 'Перевод вопроса',
    'target_phrases': 'Опорные фразы',
    'template': 'Шаблон ответа',
    'transcript': 'Расшифровка записи',
    'translation': 'Перевод',
    'type': 'Тип задания',
}
_VALUES = {
    'type': {'listening_choice': 'Аудирование с выбором', 'multiple_choice': 'Выбор ответа'},
    'prompt_role': {'question': 'Условие задания', 'audio': 'Текст аудиозаписи'},
}
_QUESTION_COUNT = 'Изменённых заданий'
_WRITING_COUNT = 'Полей письменных работ'


def _precise_units(row: dict) -> Counter[str]:
    # The staged format uses a single field name for writing and a path for a question.
    return Counter(_QUESTION_COUNT if ' / ' in change['path'] else _WRITING_COUNT
                   for change in row['changes'])


def package_totals(rows: list[dict]) -> list[tuple[str, int]]:
    counts = Counter(row['kind'] for row in rows)
    units = Counter()
    precise_units: Counter[str] = Counter()
    for row in rows:
        units[row['kind']] += row['count']
        if row['kind'] == 'lesson_rows':
            precise_units.update(_precise_units(row))
    totals = [('Файлов', len(rows))]
    for kind, label, unit in (
        ('module', 'Модулей', 'Уроков в модулях'),
        ('final_test', 'Отдельных итоговых тестов', 'Заданий в отдельных тестах'),
    ):
        if counts[kind]:
            totals.extend(((label, counts[kind]), (unit, units[kind])))
    if counts['lesson_rows']:
        totals.append(('Уроков с точечными изменениями', counts['lesson_rows']))
        totals.extend((label, precise_units[label]) for label in (_QUESTION_COUNT, _WRITING_COUNT)
                      if precise_units[label])
    return totals


def _lines(field: str, value: object) -> list[str]:
    if value is None or value == '':
        return ['Не задано']
    if isinstance(value, list):
        return [str(item) for item in value] or ['Нет вариантов']
    text = _VALUES.get(field, {}).get(value, value) if isinstance(value, str) else value
    return str(text).splitlines()


def _display_fields(before: dict, after: dict, fields: Iterable[str]) -> list[dict]:
    return [{
        'label': _FIELDS.get(field, 'Дополнительное поле'),
        'before': _lines(field, before[field]) if field in before else ['Не было'],
        'after': _lines(field, after[field]) if field in after else ['Убрано'],
    } for field in fields]


def _display_change(change: dict) -> dict:
    path = change['path']
    parts = path.split(' / ')
    if len(parts) == 1:
        label = _FIELDS.get(path, 'Поле урока')
        # Older staged writing changes keep list values serialized as JSON.
        before, after = change['before'], change['after']
        if path in ('hint_words', 'target_phrases'):
            before, after = json.loads(before), json.loads(after)
        return {'title': label, 'fields': _display_fields({path: before}, {path: after}, [path])}

    before, after = json.loads(change['before']), json.loads(change['after'])
    fields = _display_fields(before, after, sorted(before.keys() | after.keys()))
    title = f'Задание {parts[-1]}' if parts[-1].isdecimal() else 'Задание'
    if len(parts) == 4 and parts[1].isdecimal():
        title = f'Раздел {parts[1]} · {title.lower()}'
    if len(fields) == 1:
        title = f"{title} · {fields[0]['label']}"
    return {'title': title, 'fields': fields}


def display_rows(rows: list[dict]) -> list[dict]:
    return [{**row, 'display_changes': [_display_change(change) for change in row.get('changes', [])],
             'precise_units': _precise_units(row) if row['kind'] == 'lesson_rows' else {}}
            for row in rows]
