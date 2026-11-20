# ruff: noqa: RUF001
"""Lossless, bounded projection of authored theory for native and legacy clients.

We only traverse explicit theory containers. Exercise prompts, answer keys,
transcripts and arbitrary metadata are never searched recursively for prose.
Structured tables/examples are additive; every block retains its readable body.
"""

import json
import re

from app.grammar_lab.theory_schema import ordered_theory_keys

MAX_BLOCKS = 100
MAX_ROWS = 100
MAX_COLUMNS = 24
MAX_THEORY_CHARS = 200_000
MAX_THEORY_BYTES = 450_000
_MEDIA_KEYS = frozenset({"audio", "audio_url", "sound", "image", "image_url", "video", "video_url"})
_NATIVE_COLUMNS_AFTER = {"pronoun": ("possessive",), "form": ("full", "short")}
_LABELS = {
    "example": "Пример",
    "translation": "Перевод",
    "example_translation": "Перевод примера",
    "english": "Английский",
    "russian": "Русский",
    "en": "Английский",
    "ru": "Русский",
    "pronoun": "Местоимение",
    "verb": "Глагол",
    "form": "Форма",
    "note": "Примечание",
    "meaning": "Значение",
    "structure": "Схема",
    "pattern": "Модель",
    "rule": "Правило",
    "adjective": "Прилагательное",
    "present": "Настоящее",
    "past": "Прошедшее",
    "type": "Тип",
    "subject": "Подлежащее",
    "object": "Дополнение",
    "people": "Люди",
    "things": "Вещи",
    "places": "Места",
    "article": "Артикль",
    "category": "Категория",
    "usage": "Когда используем",
    "use": "Когда используем",
    "marker": "Маркер",
    "preposition": "Предлог",
    "wrong": "Неверно",
    "correct": "Верно",
    "word": "Слово",
    "direct": "Прямая речь",
    "reported": "Косвенная речь",
    "comparative": "Сравнительная степень",
    "superlative": "Превосходная степень",
    "noun": "Существительное",
    "positive": "Утверждение",
    "affirmative": "Утверждение",
    "negative": "Отрицание",
    "question": "Вопрос",
    "answer": "Ответ",
    "gerund": "Герундий",
    "modal": "Модальный глагол",
    "label": "Форма",
    "logic": "Смысл",
    "context": "Контекст",
    "register": "Стиль",
    "time_expression": "Выражение времени",
    "time_indicator": "Указатель времени",
    "if_clause": "Условие",
    "main_clause": "Главная часть",
    "phrase": "Выражение",
    "full_form": "Полная форма",
    "full": "Полная форма",
    "short": "Краткая форма",
    "possessive": "Притяжательная форма",
    "literal": "Буквально",
    "situation": "Ситуация",
    "translation_q": "Перевод вопроса",
    "translation_a": "Перевод ответа",
    "normal": "Обычный порядок",
    "inverted": "Инверсия",
    "suffix": "Суффикс",
    "full_sentence": "Полное предложение",
    "position": "Позиция",
    "quantifier": "Определитель количества",
    "active": "Действительный залог",
    "passive": "Страдательный залог",
    "statement": "Утверждение",
    "expression": "Выражение",
    "real_meaning": "Переносное значение",
    "phrasal": "Фразовый глагол",
    "idiom": "Идиома",
    "direct_question": "Прямой вопрос",
    "condition": "Условие",
    "result": "Результат",
    "base_form": "Начальная форма",
    "informal": "Разговорный стиль",
    "formal": "Формальный стиль",
    "tense": "Время",
    "case": "Случай",
    "particle": "Частица",
    "tag": "Хвостик вопроса",
    "example_bad": "Неверный пример",
    "connector": "Связка",
    "adverb": "Наречие",
    "reason": "Причина",
    "conjunction": "Союз",
    "emphasis": "Выделение",
    "mistake": "Ошибка",
    "correction": "Исправление",
    "singular": "Единственное число",
    "plural": "Множественное число",
    "countable": "Исчисляемое",
    "uncountable": "Неисчисляемое",
    "earlier": "Раньше",
    "later": "Позже",
    "examples": "Примеры",
    "explanation": "Пояснение",
    "translation_active": "Перевод действительного залога",
    "translation_passive": "Перевод страдательного залога",
    "v1": "Начальная форма (V1)",
    "v3": "Третья форма (V3)",
    "body_part": "Часть тела",
    "BrE": "Британский вариант",
    "AmE": "Американский вариант",
    "american": "Американский вариант",
    "british": "Британский вариант",
    "participle_clause": "Причастный оборот",
    "embedded": "Косвенный вопрос",
    "translation_sg": "Перевод единственного числа",
    "translation_pl": "Перевод множественного числа",
    "translation_pos": "Перевод утверждения",
    "translation_neg": "Перевод отрицания",
    "translation_positive": "Перевод утверждения",
    "translation_negative": "Перевод отрицания",
    "translation_statement": "Перевод утверждения",
    "translation_question": "Перевод вопроса",
    "with_pronoun": "С местоимением",
    "without_pronoun": "Без местоимения",
    "with_if": "С if",
    "with_inversion": "С инверсией",
    "substitution": "Замена",
    "when_to_use": "Когда используем",
    "use_where": "Когда используем",
    "trigger": "Условие выбора",
    "percentage": "Вероятность",
    "origin": "Происхождение",
    "quality": "Качество",
    "feel": "Оттенок значения",
    "less_fewer": "Less / fewer",
    "few_little": "Few / little",
    "ed_form": "Форма на -ed",
    "ing_form": "Форма на -ing",
    "ed_translation": "Перевод формы на -ed",
    "ing_translation": "Перевод формы на -ing",
    "cliché": "Клише",
    "issue": "Проблема",
    "signal": "Сигнал",
    "base": "Основа",
    "question_c": "Вопрос с исчисляемым",
    "question_u": "Вопрос с неисчисляемым",
    "error": "Ошибка",
    "alternative": "Другой вариант",
}


def project_theory(content, plain):
    if not isinstance(content, dict):
        return []
    from app.api.native_lessons import NativeLessonError

    blocks = []
    total = 0

    def fail():
        raise NativeLessonError("unsupported_lesson", 422)

    def cell(value, depth=0):
        if depth > 4:
            fail()
        if isinstance(value, dict):
            return " · ".join(
                filter(None, (cell(v, depth + 1) for k, v in value.items() if str(k).lower() not in _MEDIA_KEYS))
            )
        if isinstance(value, list):
            if len(value) > MAX_ROWS:
                fail()
            return "\n".join(filter(None, (cell(v, depth + 1) for v in value)))
        return plain(value)

    def add(title, body, kind="text", **structured):
        nonlocal total
        body = plain(body)
        if not body:
            return
        title = plain(title) or "Правило"
        total += len(title) + len(body)
        if len(blocks) >= MAX_BLOCKS or total > MAX_THEORY_CHARS:
            fail()
        blocks.append({"title": title, "body": body, "kind": kind, **structured})

    def first(item, keys):
        return next((plain(item.get(key)) for key in keys if plain(item.get(key))), "")

    def examples(items, title="Примеры"):
        if not isinstance(items, list):
            return
        if len(items) > MAX_ROWS:
            fail()
        values = []
        for item in items:
            if isinstance(item, dict):
                english = prose(item, ("word", "english", "sentence", "example", "en", "text", "question"))
                translation = prose(item, ("russian", "translation", "example_translation", "ru"))
                explanation = prose(item, ("explanation", "note"))
                answer = cell(item.get("answer"))
                if answer:
                    explanation = "\n".join(filter(None, [explanation, "Ответ: " + answer]))
            else:
                english, translation, explanation = plain(item), "", ""
            if english or translation or explanation:
                values.append(
                    {"english": english, "translation": translation or None, "explanation": explanation or None}
                )
        if values:
            add(
                title,
                "\n\n".join("\n".join(filter(None, value.values())) for value in values),
                "examples",
                examples=values,
            )

    def table(value, title):
        headers = []
        keys = []
        if isinstance(value, dict):
            title = plain(value.get("title")) or title
            header_source = value.get("headers") or value.get("columns") or []
            if not isinstance(header_source, list):
                fail()
            for h in header_source:
                if isinstance(h, dict):
                    key = first(h, ("key", "field", "id"))
                    keys.append(key)
                    headers.append(first(h, ("label", "title", "name")) or _LABELS.get(key, key))
                else:
                    keys.append(plain(h))
                    headers.append(plain(h))
            if any(key in value for key in ("rows", "table", "headers", "columns")):
                value = value.get("rows") or value.get("table") or []
            else:
                # Standalone Grammar Lab seeds use a compact mapping such as
                # affirmative/negative/question rather than a rows wrapper.
                headers = ["Форма", "Схема"]
                value = [
                    [_LABELS.get(key, str(key).replace("_", " ")), cell(value[key])]
                    for key in ordered_theory_keys(sorted(value, key=str), after=_NATIVE_COLUMNS_AFTER)
                    if key != "title" and str(key).lower() not in _MEDIA_KEYS
                ]
        if not isinstance(value, list) or not value:
            return
        if len(value) > MAX_ROWS:
            fail()
        if all(isinstance(row, dict) for row in value):
            authored_keys = list(dict.fromkeys(k for row in value for k in row if str(k).lower() not in _MEDIA_KEYS))
            authored_keys = ordered_theory_keys(sorted(authored_keys, key=str), after=_NATIVE_COLUMNS_AFTER)
            # Named column definitions retain their order. Scalar header lists
            # are labels, not necessarily JSON keys; infer keys from the rows.
            if not keys or not all(key in authored_keys for key in keys):
                keys = authored_keys
            else:
                for key in authored_keys:
                    if key not in keys:
                        keys.append(key)
                        headers.append(_LABELS.get(str(key), str(key).replace("_", " ").capitalize()))
            if not headers:
                headers = [_LABELS.get(str(k), re.sub(r"[_-]+", " ", str(k)).capitalize()) for k in keys]
            rows = [[cell(row.get(key)) for key in keys] for row in value]
        else:
            rows = [[cell(v) for v in row] if isinstance(row, list) else [cell(row)] for row in value]
        columns = max([len(headers), *(len(row) for row in rows)], default=0)
        if columns > MAX_COLUMNS:
            fail()
        if not headers:
            headers = [""] * columns
        headers += [""] * (columns - len(headers))
        rows = [row + [""] * (columns - len(row)) for row in rows]
        rows = [row for row in rows if any(row)]
        body = "\n".join(" · ".join(filter(None, row)) for row in rows)
        if body:
            # Legacy readers get labels too, while native readers retain cells.
            legacy = (" · ".join(filter(None, headers)) + "\n" if any(headers) else "") + body
            add(title, legacy, "table", table={"headers": headers, "rows": rows})

    def prose(item, keys):
        return "\n".join(dict.fromkeys(filter(None, (cell(item.get(k)) for k in keys))))

    def rules(items, title):
        if not isinstance(items, list):
            return
        if len(items) > MAX_ROWS:
            fail()
        for rule in items:
            if isinstance(rule, dict):
                add(
                    first(rule, ("title", "subtitle")) or title,
                    prose(
                        rule,
                        (
                            "rule",
                            "description",
                            "content",
                            "body",
                            "text",
                            "explanation",
                            "formula",
                            "pattern",
                            "structure",
                            "usage",
                        ),
                    ),
                )
                examples(rule.get("examples"))
                table(rule.get("table"), title)
                add("Обрати внимание", prose(rule, ("note", "notes", "important_notes")), "note")
            else:
                add(title, plain(rule))

    wrapper = content.get("grammar_explanation")
    source = wrapper if isinstance(wrapper, dict) else content
    intro = first(source, ("introduction", "description", "content", "text"))
    add(first(source, ("title",)) or "Перед практикой", intro)
    rule = cell(source.get("rule"))
    if rule and rule != intro:
        add("Главное правило", rule)
    tldr = cell(source.get("tldr"))
    if tldr and tldr not in (intro, rule):
        add("Коротко", tldr, "note")
    add("Схема", prose(source, ("formula", "pattern", "structure")))
    table(source.get("table"), "Формы и примеры")
    table(source.get("summary_table"), "Краткая таблица")
    rules(source.get("rules"), "Правило")
    sections = source.get("sections") or []
    if not isinstance(sections, list):
        fail()
    for section in sections:
        if not isinstance(section, dict):
            continue
        title = first(section, ("title", "subtitle")) or "Правило"
        add(
            title,
            prose(
                section, ("rule", "content", "body", "text", "description", "formula", "pattern", "structure", "usage")
            ),
        )
        rules(section.get("rules"), title)
        table(section.get("table"), title)
        examples(section.get("examples"), title)
        add("Обрати внимание", prose(section, ("note", "notes")), "note")
    examples(source.get("examples"))
    # Some imported wrappers keep examples alongside grammar_explanation.
    if source is not content:
        examples(content.get("examples"))
    for key, title in [
        ("important_notes", "Обрати внимание"),
        ("notes", "Обрати внимание"),
        ("summary", "Итоги"),
        ("common_mistakes", "Частые ошибки"),
        ("tips", "Советы"),
    ]:
        value = source.get(key)
        if key == "common_mistakes" and isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            table(value, title)
        else:
            add(title, cell(value), "note")
    if len(json.dumps(blocks, ensure_ascii=True).encode("utf-8")) > MAX_THEORY_BYTES:
        fail()
    return blocks
