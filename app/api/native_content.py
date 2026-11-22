"""Course content projection and grading shared by the native lesson API.

Only presentation is adapted here. Objective answers use the course's existing
pure graders; completed/practice/self-review remain separate from accuracy.
"""

from copy import deepcopy
import json
import random
import re
from urllib.parse import urlsplit

QUIZZES = {
    "quiz",
    "ordering_quiz",
    "translation_quiz",
    "listening_quiz",
    "dialogue_completion_quiz",
    "final_test",
}
READINGS = {"reading", "text", "listening_immersion_quiz", "listening_immersion"}
INPUTS = {
    "dictation",
    "audio_fill_blank",
    "translation",
    "sentence_correction",
    "sentence_completion",
}
ACTIVITIES = {"writing_prompt", "pronunciation", "shadow_reading", "idiom"}
EXTENDED = (
    QUIZZES | READINGS | INPUTS | ACTIVITIES | {"grammar", "collocation_matching", "matching"}
)
CHOICE = {"multiple_choice", "dialogue_completion", "listening_choice", "reading_comprehension"}
TEXT = {
    "",
    "fill_blank",
    "fill-blank",
    "fill_in_blank",
    "fill-in-blank",
    "translation",
    "transformation",
    "error_correction",
}
FILL_BLANKS = {"fill_blank", "fill-blank", "fill_in_blank", "fill-in-blank"}
NATIVE_PROJECTION_VERSION = 2


def _error(code="unsupported_lesson", status=422):
    from app.api.native_lessons import NativeLessonError

    raise NativeLessonError(code, status)


def _plain(value):
    from app.api.native_lessons import plain

    return plain(value)


def content_for(lesson):
    value = lesson.content
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            _error()
    if not isinstance(value, dict):
        _error()
    return deepcopy(value)


def is_extended(lesson):
    if getattr(lesson, "_native_challenge", False):
        return True
    if lesson.type not in ("grammar", "quiz"):
        return True
    c = content_for(lesson)
    if c.get("learning_steps"):
        return True
    rows = c.get("exercises" if lesson.type == "grammar" else "questions")
    if rows is not None and not isinstance(rows, list):
        return True
    if rows is None and lesson.type == "quiz":
        return True
    if any(c.get(k) for k in ("audio", "audio_url", "video", "video_url")):
        return True
    simple = TEXT | {"multiple_choice", "true_false", "reorder"}
    return len(rows or []) > 100 or any(
        not isinstance(q, dict)
        or q.get("type", "") not in simple
        or (q.get("type") in FILL_BLANKS and q.get("options")
            and (lesson.type == "grammar" or q.get("type") != "fill_blank"))
        or (q.get("type") == "reorder" and (q.get("words") or q.get("tokens")))
        or any(
            q.get(k)
            for k in (
                "audio",
                "audio_url",
                "audio_clip_url",
                "image",
                "image_url",
                "video",
                "video_url",
            )
        )
        for q in rows or []
    )


def media_url(value, folder="audio"):
    if isinstance(value, dict):
        value = value.get("url") or value.get("src")
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.startswith("[sound:") and value.endswith("]"):
        value = value[7:-1]
    if len(value) > 4096:
        _error()
    if value.startswith("https://"):
        parts = urlsplit(value)
        return value if parts.hostname and not parts.username and not parts.password else None
    if "://" in value or value.startswith("//") or ".." in value.split("/"):
        return None
    if value.startswith("/"):
        return value
    if value.startswith("static/"):
        return "/" + value
    if value.startswith("audio/"):
        return "/static/" + value
    return "/static/" + folder + "/" + value


def _pair(pair):
    from app.curriculum.grading import _pair_left, _pair_right

    if not isinstance(pair, dict):
        _error()
    return str(pair.get("phrase") or _pair_left(pair)), str(_pair_right(pair))


def rows_for(lesson, content=None):
    c = content if content is not None else content_for(lesson)
    if lesson.type == "grammar":
        rows = c.get("exercises") or []
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            _error()
        return [
            {**r, "type": "match" if r.get("type") == "matching" else r.get("type", "")}
            for r in rows
        ]
    if lesson.type == "final_test":
        sections = c.get("test_sections") or c.get("sections")
        rows = []
        if sections:
            for section in sections:
                for row in section.get("exercises") or section.get("questions") or []:
                    rows.append(
                        {
                            **row,
                            "_section_label": _plain(
                                section.get("title") or section.get("section")
                            ),
                        }
                    )
        else:
            rows = c.get("questions") or c.get("exercises") or []
        # Same legacy low-context-cloze policy as the website final-test form.
        from app.curriculum.routes.grammar_quiz_lessons import (
            _filter_final_test_questions_for_student,
        )

        return _filter_final_test_questions_for_student(rows, lesson_id=lesson.id)
    if lesson.type in READINGS:
        return c.get("comprehension_questions") or c.get("exercises") or c.get("questions") or []
    if lesson.type in QUIZZES:
        return [
            {
                **r,
                "type": "true_false" if r.get("type") == "tf" else r.get("type", "multiple_choice"),
            }
            for r in c.get("questions") or c.get("exercises") or []
        ]
    if lesson.type == "dictation":
        from app.curriculum.routes.lessons import _dictation_items_from_content

        if c.get("gaps"):
            return [
                {
                    "type": "dictation_gap",
                    "prompt": _plain(g.get("hint")) or "Пропущенное слово",
                    "answer": g["display"],
                }
                for g in _dictation_items_from_content(c, 0)
            ]
        return [
            {
                "type": "dictation_full",
                "prompt": "Запиши услышанный текст",
                "answer": c.get("transcript", ""),
            }
        ]
    if lesson.type == "translation":
        from app.curriculum.routes.lessons import _translation_items_from_content

        return _translation_items_from_content(c)
    if lesson.type == "sentence_correction":
        return c.get("items") or [c]
    if lesson.type in ("collocation_matching", "matching"):
        return [{"type": "matching", "pairs": c.get("pairs") or []}]
    return c.get("items") or []


def _dialogue_text(value):
    """Only authored speaker/text fields are visible, never arbitrary metadata."""
    if not isinstance(value, list):
        return _plain(value)
    if len(value) > 100:
        _error()
    lines = []
    for line in value:
        if isinstance(line, str):
            text = _plain(line)
        elif isinstance(line, dict):
            text = _plain(line.get("text"))
            # Some authored blanks include surrounding words. Keep that useful
            # partial sentence, but never print a filled answer flagged blank.
            if line.get("blank") is True and not re.search(r"_{2,}", text):
                text = "___"
            speaker = _plain(line.get("speaker"))
            if speaker and text:
                text = f"{speaker}: {text}"
        else:
            _error()
        if text:
            lines.append(text)
    return _plain("\n".join(lines))


def _prompt(row):
    # In listening_choice, text/sentence/dialogue are listening material. The
    # authored question remains visible; transcripts/audio_text never become a
    # fallback question simply because another display field is empty. Reading
    # questions retain their explicitly authored text.
    keys = ("question", "prompt") if row.get("type") == "listening_choice" else (
        "question", "prompt", "text", "sentence", "incorrect_sentence",
        "dialogue", "russian", "statement",
    )
    values = (_dialogue_text(row.get(key)) if key == "dialogue" else _plain(row.get(key)) for key in keys)
    return "\n".join(dict.fromkeys(filter(None, values)))


def _sentence_prompt(row):
    prefix = _prompt(row) or _plain(row.get("text_with_gap"))
    suffix = _plain(row.get("prompt_after"))
    if not prefix and not suffix and not _visible_context(row):
        _error()
    if not re.search(r"_{2,}", prefix):
        prefix = (prefix + " ___").strip()
    sentence = " ".join(filter(None, (prefix, suffix)))
    # Empty-prefix transformations often continue with a comma; keep normal
    # sentence punctuation instead of an artificial space before it.
    return _plain(re.sub(r"\s+([,.;:!?])", r"\1", sentence))


def _visible_context(row):
    value = _plain(row.get("context"))
    return "" if value.casefold() == "vocab use" else value


def _question_hints(lesson, row, index, instruction):
    values = [instruction]
    hint = _plain(row.get("hint"))
    if hint:
        values.append("Подсказка: " + hint)
    if lesson.type == "translation" and content_for(lesson).get("mode") not in ("open", "rubric"):
        bank = row.get("hint_words") or []
        if not isinstance(bank, list) or len(bank) > 100 or any(not isinstance(word, str) for word in bank):
            _error()
        words = [_plain(word) for word in bank]
        if any(not word for word in words):
            _error()
        if words:
            # Keep multiword chunks and duplicate tokens intact. Do not derive
            # a bank from the private English reference or accepted answers.
            random.Random(f"native:hints:{lesson.id}:{index}").shuffle(words)
            values.append("Слова для перевода: " + " · ".join(words))
    return _plain("\n".join(filter(None, values)))


def _question(lesson, row, index):
    from app.curriculum.language_support import language_support_mode, question_translation

    if not isinstance(row, dict):
        _error()
    kind = row.get("type", "multiple_choice" if lesson.type in QUIZZES else "")
    question = {
        "id": str(index),
        "prompt": _sentence_prompt(row) if lesson.type == "sentence_completion" else _prompt(row),
        "instruction": _plain(row.get("instruction")),
        "options": [],
        "input": "text",
        "translation": (
            _plain(question_translation(row))
            if language_support_mode(lesson) in ("inline", "toggle")
            else None
        ),
        "audio_url": media_url(
            row.get("audio_url") or row.get("audio_clip_url") or row.get("audio")
        ),
        "image_url": media_url(row.get("image_url") or row.get("image"), "images"),
        "video_url": media_url(row.get("video_url") or row.get("video"), "video"),
        "section": row.get("_section_label"),
    }
    if kind in CHOICE or (kind in FILL_BLANKS and row.get("options")):
        choices = row.get("options")
        if (
            not isinstance(choices, list)
            or not 2 <= len(choices) <= 30
            or not all(isinstance(x, str) and _plain(x) for x in choices)
        ):
            _error()
        question["input"] = "choice"
        question["options"] = [{"value": str(i), "label": _plain(v)} for i, v in enumerate(choices)]
    elif kind in ("true_false", "tf"):
        question["input"] = "choice"
        question["options"] = [
            {"value": "true", "label": "Верно / True"},
            {"value": "false", "label": "Неверно / False"},
        ]
    elif kind in ("matching", "match"):
        pairs = row.get("pairs") or []
        if not pairs or len(pairs) > 50:
            _error()
        values = [_pair(p) for p in pairs]
        if any(not a or not b for a, b in values):
            _error()
        question["input"] = "match"
        question["left_options"] = [
            {"value": str(i), "label": _plain(a)} for i, (a, _) in enumerate(values)
        ]
        question["options"] = [
            {"value": str(i), "label": _plain(b)} for i, (_, b) in enumerate(values)
        ]
        question["prompt"] = question["prompt"] or "Подбери соответствия"
    elif kind in ("ordering", "reorder", "sentence_builder"):
        words = row.get("words") or row.get("tokens")
        if (
            not isinstance(words, list)
            or not 1 <= len(words) <= 80
            or not all(isinstance(w, str) and _plain(w) for w in words)
        ):
            _error()
        question["input"] = "order"
        question["options"] = [{"value": str(i), "label": _plain(w)} for i, w in enumerate(words)]
        question["prompt"] = question["prompt"] or "Собери предложение"
    elif kind in TEXT or kind in ("dictation_gap", "dictation_full"):
        if kind == "dictation_full":
            question["input"] = "long_text"
    else:
        _error()
    if lesson.type in (
        "translation",
        "sentence_correction",
        "sentence_completion",
        "audio_fill_blank",
    ):
        question["prompt"] = (
            _sentence_prompt(row) if lesson.type == "sentence_completion"
            else _prompt(row) or _plain(row.get("text_with_gap"))
        )
        if lesson.type == "translation" and content_for(lesson).get("mode") in ("open", "rubric"):
            question["input"] = "translation_review"
        if lesson.type == "audio_fill_blank" and row.get("options"):
            question["input"] = "choice"
            question["options"] = [
                {"value": str(i), "label": _plain(v)} for i, v in enumerate(row["options"])
            ]
    if lesson.type == "dictation" and content_for(lesson).get("gap_text"):
        question["context"] = re.sub(
            r"\{(\d+)\}", lambda m: f" [{int(m.group(1))+1}] ____ ", content_for(lesson)["gap_text"]
        )
        question["prompt"] = f"Пропуск {index+1}" + (
            f' · подсказка: {question["prompt"]}' if question["prompt"] else ""
        )
    context = _visible_context(row)
    if context and "context" not in question:
        question["context"] = context
    if not question["prompt"]:
        _error()
    if not question["instruction"]:
        question["instruction"] = {
            "match": "Подбери пары",
            "order": "Расположи слова по порядку",
            "choice": "Выбери ответ",
        }.get(question["input"], "Введи ответ")
    if lesson.type != "final_test":
        question["instruction"] = _question_hints(lesson, row, index, question["instruction"])
    # Final module tests deliberately offer no theory during the attempt.
    if lesson.type != "final_test" and language_support_mode(lesson) in ("inline", "toggle"):
        from app.grammar_lab.guided_learning import question_help

        help_blocks = question_help(content_for(lesson), row, index, len(rows_for(lesson)))
        if help_blocks:
            question["theory_help"] = help_blocks
    random.Random(f"native:{lesson.id}:{index}").shuffle(question["options"])
    return question


def theory_for(lesson):
    from app.api.native_lessons import _theory

    c = content_for(lesson)
    if lesson.type in ("audio_fill_blank", "listening_quiz"):
        return []
    if lesson.type == "dictation" and not c.get("gap_text"):
        return []
    if lesson.type == "listening_immersion" and rows_for(lesson, c):
        return []
    blocks = _theory(c)
    text = c.get("text") or c.get("content")
    if isinstance(text, dict):
        lines = text.get("lines") or text.get("paragraphs") or []
        for line in lines:
            body = _plain(line.get("text")) if isinstance(line, dict) else _plain(line)
            if isinstance(line, dict):
                from app.curriculum.language_support import language_support_mode

                if language_support_mode(lesson) == "inline" and line.get("translation"):
                    body += "\n" + _plain(line["translation"])
            if body:
                block = {"title": _plain(text.get("title")) or "Чтение", "body": body}
                if (
                    isinstance(line, dict)
                    and language_support_mode(lesson) == "toggle"
                    and line.get("translation")
                ):
                    block["translation"] = _plain(line["translation"])
                blocks.append(block)
    if lesson.type == "listening_immersion" and not rows_for(lesson, c) and isinstance(text, str):
        reference = _plain(text)
        if reference:
            if any(block.get("body") == reference for block in blocks):
                blocks = [{**block, "title": "Текст записи"} if block.get("body") == reference else block
                          for block in blocks]
            else:
                blocks.append({"title": "Текст записи", "body": reference})
    if lesson.type == "writing_prompt":
        for key, title in [
            ("template", "Шаблон"),
            ("hint_words", "Полезные слова"),
            ("target_phrases", "Используй в тексте"),
        ]:
            value = c.get(key)
            if isinstance(value, list):
                value = " · ".join(map(_plain, value))
            if _plain(value):
                blocks.append({"title": title, "body": _plain(value)})
    if lesson.type == "shadow_reading" and _plain(c.get("transcript")):
        blocks.append({"title": "Повторяй за записью", "body": _plain(c["transcript"])})
    if lesson.type == "idiom":
        blocks += [
            {
                "title": _plain(i.get("phrase")),
                "body": "\n".join(
                    filter(None, [_plain(i.get("meaning")), _plain(i.get("example"))])
                ),
            }
            for i in c.get("items") or []
        ]
    if lesson.type == "dictation" and c.get("gap_text"):
        blocks = [
            {
                "title": "Текст с пропусками",
                "body": re.sub(
                    r"\{(\d+)\}", lambda m: f" [{int(m.group(1))+1}] ____ ", c["gap_text"]
                ),
            }
        ]
    return blocks


def project(lesson):
    if lesson.type not in EXTENDED:
        _error()
    c = content_for(lesson)
    if lesson.type == "writing_prompt":
        from app.curriculum.language_support import language_support_mode, question_translation
        from app.curriculum.routes.lessons import (
            _DEFAULT_WRITING_CHECKLIST,
            _writing_words_required,
        )

        checklist = c.get("checklist") or _DEFAULT_WRITING_CHECKLIST
        q = {
            "id": "0",
            "prompt": _plain(c.get("prompt")) or lesson.title,
            "instruction": "Напиши свой текст и проверь его по списку",
            "input": "essay",
            "options": [],
            "checklist": list(map(_plain, checklist)),
            "min_words": (
                int(c.get("min_words") or (0 if c.get("min_sentences") else 50))
                if _writing_words_required(lesson)
                else 0
            ),
            "min_sentences": int(c.get("min_sentences") or 0),
            "min_checklist": min(
                int(
                    c.get("min_checklist")
                    or (
                        3
                        if c.get("mode") == "guided"
                        or c.get("min_sentences")
                        or c.get("hint_words")
                        or c.get("template")
                        else 2
                    )
                ),
                max(2, len(checklist)),
            ),
            "translation": (
                _plain(question_translation(c))
                if language_support_mode(lesson) in ("inline", "toggle")
                else None
            ),
        }
        questions = [q]
    elif lesson.type == "pronunciation":
        questions = [
            {
                "id": str(i),
                "prompt": _plain(row.get("word")),
                "instruction": _plain(row.get("pronunciation_hint")) or "Произнеси слово вслух",
                "input": "speech",
                "options": [],
                "translation": None,
            }
            for i, row in enumerate(c.get("items") or [])
        ]
    elif lesson.type in ("shadow_reading", "idiom") or (
        lesson.type in READINGS and not rows_for(lesson, c)
    ):
        questions = [
            {
                "id": "0",
                "prompt": (
                    "Я прослушал запись и повторил вслух"
                    if lesson.type == "shadow_reading"
                    else (
                        "Я изучил все выражения" if lesson.type == "idiom" else "Я закончил занятие"
                    )
                ),
                "instruction": "Подтверди выполненную практику",
                "input": "confirm",
                "options": [],
                "translation": None,
            }
        ]
    else:
        rows = rows_for(lesson, c)
        if not isinstance(rows, list) or not rows:
            _error()
        questions = [_question(lesson, row, i) for i, row in enumerate(rows)]
    if not questions or len(questions) > 500 or any(not q["prompt"] for q in questions):
        _error()
    return questions


def extras(lesson):
    c = content_for(lesson)
    assessment = "graded"
    if lesson.type in READINGS:
        assessment = "practice" if rows_for(lesson, c) else "self_assessed"
    if lesson.type in ACTIVITIES:
        assessment = {"writing_prompt": "writing", "pronunciation": "pronunciation"}.get(
            lesson.type, "self_assessed"
        )
    if lesson.type == "translation" and c.get("mode") in ("open", "rubric"):
        assessment = "self_review"
    return {
        "assessment": assessment,
        "audio_url": media_url(c.get("audio_url") or c.get("audio")),
        "video_url": media_url(c.get("video_url") or c.get("video"), "video"),
        "theory": theory_for(lesson),
        "instruction": _plain(c.get("instruction") or c.get("description")),
    }


def _json_answer(value):
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        _error("invalid_input", 400)


def _converted(row, q, value, grammar=False):
    form = q.get("input")
    if form == "choice":
        if value not in {o["value"] for o in q["options"]}:
            _error("invalid_input", 400)
        if row.get("type") in ("true_false", "tf"):
            return value
        if row.get("type") in FILL_BLANKS and (grammar or row.get("type") != "fill_blank"):
            return row["options"][int(value)]
        # Existing quiz graders accept source option indexes; audio-fill uses text.
        return value
    if form == "order":
        indexes = _json_answer(value)
        words = row.get("words") or row.get("tokens") or []
        if (
            not isinstance(indexes, list)
            or len(indexes) != len(words)
            or not all(type(index) is str for index in indexes)
            or set(indexes) != set(map(str, range(len(words))))
        ):
            _error("invalid_input", 400)
        if grammar and row.get("type") == "sentence_builder":
            expected = row.get("correct_order") or []
            return (
                [int(i) for i in indexes]
                if expected and isinstance(expected[0], int)
                else [words[int(i)] for i in indexes]
            )
        return " ".join(words[int(i)] for i in indexes)
    if form == "match":
        indexes = _json_answer(value)
        pairs = row.get("pairs") or []
        if (
            not isinstance(indexes, dict)
            or set(indexes) != set(map(str, range(len(pairs))))
            or any(
                type(v) is not str or v not in set(map(str, range(len(pairs))))
                for v in indexes.values()
            )
            or len(set(indexes.values())) != len(pairs)
        ):
            _error("invalid_input", 400)
        if grammar:
            return indexes
        return {_pair(pairs[int(i)])[0]: _pair(pairs[int(j)])[1] for i, j in indexes.items()}
    return value


def display_answer(question, value):
    """Use learner-visible labels in feedback, never transport indexes/JSON."""
    options = {option["value"]: option["label"] for option in question.get("options", [])}
    if question.get("input") == "choice":
        return options.get(value, _plain(value))
    if question.get("input") == "match":
        left = {option["value"]: option["label"] for option in question.get("left_options", [])}
        indexes = _json_answer(value)
        return "\n".join(f"{left[i]} → {options[j]}" for i, j in indexes.items())
    if question.get("input") == "order":
        return " ".join(options[index] for index in _json_answer(value))
    return _plain(value)


def matching_answer(row):
    return "\n".join(f"{_plain(a)} → {_plain(b)}" for a, b in map(_pair, row.get("pairs") or []))


def grade(lesson, questions, answers, passing):
    """Return (grade fields, per-question feedback, assessment, completion)."""
    from app.curriculum import grading as graders

    c = content_for(lesson)
    t = lesson.type
    assessment = extras(lesson)["assessment"]
    rows = rows_for(lesson, c)
    feedback = []
    payload = {}
    telemetry = {}

    def fb(q, correct, answer, expected="", explanation=""):
        return {
            "id": q["id"],
            "prompt": q["prompt"],
            "correct": bool(correct),
            "answer": _plain(answer),
            "expected": _plain(expected),
            "explanation": _plain(explanation),
        }

    if t in QUIZZES or t == "grammar" or (t in READINGS and rows):
        converted = {
            q["id"]: _converted(row, q, answers[q["id"]], t == "grammar")
            for row, q in zip(rows, questions, strict=True)
        }
        result = (
            graders.process_grammar_submission
            if t == "grammar"
            else graders.process_quiz_submission
        )(rows, converted)
        if t == "grammar" and c.get("learning_steps"):
            from app.grammar_lab.guided_learning import grade_guided_answers

            result = grade_guided_answers(rows, converted)
        for row, q in zip(rows, questions, strict=True):
            checked = result["feedback"].get(q["id"], {})
            expected = (
                checked.get("correct_matches")
                or checked.get("correct_answer")
                or checked.get("correct_pairs")
                or ""
            )
            if isinstance(expected, dict):
                expected = "\n".join(f"{a} → {b}" for a, b in expected.items())
            elif isinstance(expected, list):
                if q.get("input") == "order":
                    labels = {option["value"]: option["label"] for option in q["options"]}
                    expected = " ".join(labels.get(str(value), str(value)) for value in expected)
                else:
                    expected = " / ".join(map(str, expected))
            if q.get("input") == "match":
                expected = matching_answer(row)
            given = display_answer(q, answers[q["id"]])
            if q.get("input") == "choice" and row.get("options"):
                if (
                    t == "grammar"
                    and str(expected).isdigit()
                    and int(str(expected)) < len(row["options"])
                ):
                    expected = row["options"][int(str(expected))]
            feedback.append(
                fb(
                    q,
                    checked.get("status") == "correct" or checked.get("is_correct") is True,
                    given,
                    expected,
                    checked.get("explanation") or row.get("explanation"),
                )
            )
    elif t in (
        "dictation",
        "audio_fill_blank",
        "translation",
        "sentence_correction",
        "sentence_completion",
    ):
        values = [answers[q["id"]] for q in questions]
        if t == "audio_fill_blank":
            values = [
                row["options"][int(v)] if q.get("input") == "choice" else v
                for row, q, v in zip(rows, questions, values, strict=True)
            ]
            result = graders.grade_audio_fill_blank(values, rows, passing_score=passing)
        elif t == "translation":
            tokens = []
            texts = []
            for v in values:
                parsed = _json_answer(v) if assessment == "self_review" else {"text": v}
                if not isinstance(parsed, dict) or not isinstance(parsed.get("text"), str):
                    _error("invalid_input", 400)
                texts.append(parsed["text"])
                tokens.append(parsed.get("review_token"))
            if assessment == "self_review":
                from app.curriculum.translation_review import review_submission

                result = review_submission(lesson, _user_id(), rows, texts, tokens)
                if not result.get("success"):
                    _error("review_required", 409)
            else:
                result = graders.grade_translation_multi(texts, rows, passing_score=passing)
            telemetry["writing_text"] = "\n".join(texts)
        elif t == "sentence_correction":
            result = graders.grade_sentence_correction_multi(values, rows, passing_score=passing)
            telemetry["writing_text"] = "\n".join(values)
        elif t == "sentence_completion":
            result = graders.grade_sentence_completion(values, rows, passing_score=passing)
        else:
            reference = (
                " ".join(row["answer"] for row in rows)
                if c.get("gaps")
                else c.get("transcript", "")
            )
            result = graders.grade_dictation(" ".join(values), reference, passing_score=passing)
            telemetry["listening"] = True
            result["correct_items"] = result["correct_words"]
            result["total_items"] = result["total_words"]
        items = result.get("item_results") or []
        for index, q in enumerate(questions):
            checked = items[index] if index < len(items) else {}
            if t == "dictation":
                if c.get("gaps"):
                    single = graders.grade_dictation(
                        values[index], rows[index]["answer"], passing_score=passing
                    )
                    checked = {
                        "correct": single["passed"],
                        "answer": rows[index]["answer"],
                        "user_answer": values[index],
                    }
                else:
                    checked = {
                        "correct": result["passed"],
                        "answer": reference if result["passed"] else "",
                        "user_answer": values[index],
                    }
            feedback.append(
                fb(
                    q,
                    checked.get("correct") is True or checked.get("status") == "matched",
                    checked.get("user_answer") or checked.get("answer") or values[index],
                    (
                        checked.get("answer") or checked.get("reference_answer")
                        if result.get("passed")
                        else ""
                    ),
                    rows[index].get("explanation", ""),
                )
            )
        if t == "audio_fill_blank":
            telemetry["listening"] = True
    elif t in ("matching", "collocation_matching"):
        row = rows[0]
        q = questions[0]
        matches = _converted(row, q, answers["0"])
        if t == "collocation_matching":
            submitted = [{"phrase": a, "translation": b} for a, b in matches.items()]
            result = graders.grade_collocation_matching(
                submitted, c.get("pairs") or [], passing_score=passing
            )
            correct = result["correct_items"]
            total = result["total_items"]
        else:
            result = graders.process_matching_submission(c.get("pairs") or [], matches)
            correct = result["correct_answers"]
            total = result["total_questions"]
        feedback = [
            fb(
                q,
                result["score"] >= passing,
                "\n".join(f"{a} → {b}" for a, b in matches.items()),
                "",
                "Подбор пар проверен сервером.",
            )
        ]
        result["correct_items"] = correct
        result["total_items"] = total
    elif t == "writing_prompt":
        value = _json_answer(answers["0"])
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("text"), str)
            or not isinstance(value.get("checked"), list)
        ):
            _error("invalid_input", 400)
        writing = _writing_requirements(lesson, c, value)
        completed = writing["completed"]
        text = value["text"].strip()
        telemetry["writing_text"] = text
        telemetry["writing_checklist"] = writing
        result = {
            "score": None,
            "passed": completed,
            "correct_items": int(completed),
            "total_items": 1,
            **writing,
        }
        feedback = [
            fb(
                questions[0],
                completed,
                text,
                "",
                f"Слов: {writing['word_count']}. Предложений: {writing['sentence_count']}. Пункты самопроверки: {writing['checked_count']}/{writing['checklist_min']}.",
            )
        ]
    elif t == "pronunciation":
        attempts = []
        for q in questions:
            value = _json_answer(answers[q["id"]])
            if (
                not isinstance(value, dict)
                or type(value.get("self_assessed", False)) is not bool
                or not isinstance(value.get("recognized", ""), str)
            ):
                _error("invalid_input", 400)
            recognized = value.get("recognized", "").strip()[:500]
            self_assessed = value.get("self_assessed", False)
            if not recognized and not self_assessed:
                _error("answers_required", 400)
            checked = (
                graders.grade_pronunciation_match(recognized, q["prompt"])
                if recognized and not self_assessed
                else {"matched": False}
            )
            attempts.append(
                {
                    "word": q["prompt"],
                    "recognized": recognized if not self_assessed else "",
                    "matched": checked["matched"],
                }
            )
            feedback.append(
                fb(
                    q,
                    checked["matched"],
                    recognized or "Самопроверка",
                    q["prompt"],
                    (
                        "Сравнивается распознанный текст, а не качество акцента."
                        if not self_assessed
                        else "Ты выполнил практику с самостоятельной проверкой."
                    ),
                )
            )
        telemetry["pronunciation"] = attempts
        result = {
            "score": None,
            "passed": True,
            "correct_items": sum(a["matched"] for a in attempts),
            "total_items": len(attempts),
        }
    elif assessment == "self_assessed":
        if any(answers[q["id"]] != "confirmed" for q in questions):
            _error("answers_required", 400)
        result = {
            "score": None,
            "passed": True,
            "correct_items": len(questions),
            "total_items": len(questions),
        }
        feedback = [
            fb(
                q,
                True,
                "Практика выполнена",
                "",
                "Завершение подтверждено тобой; это не экзаменационная оценка.",
            )
            for q in questions
        ]
    else:
        _error()
    if t in ("listening_quiz", "listening_immersion", "listening_immersion_quiz"):
        telemetry["listening"] = True
    result["passed"] = result.get("passed", (result.get("score") or 0) >= passing)
    completed = True if assessment == "practice" else result["passed"]
    result["_telemetry"] = telemetry
    return result, feedback, assessment, completed


def _user_id():
    from flask_login import current_user

    return current_user.id


def _writing_requirements(lesson, c, value):
    from app.curriculum.routes.lessons import _DEFAULT_WRITING_CHECKLIST, _writing_words_required

    checklist = c.get("checklist") or _DEFAULT_WRITING_CHECKLIST
    checked = {v for v in value["checked"] if isinstance(v, str) and v in checklist}
    mode = c.get("mode") or (
        "guided"
        if c.get("min_sentences") or c.get("hint_words") or c.get("template")
        else "structured"
    )
    minimum = min(
        int(c.get("min_checklist") or (3 if mode == "guided" else 2)), max(len(checklist), 2)
    )
    min_sentences = int(c.get("min_sentences") or 0)
    min_words = (
        int(c.get("min_words") or (0 if min_sentences else 50))
        if _writing_words_required(lesson)
        else 0
    )
    text = value["text"].strip()
    words = len(text.split())
    sentences = len([x for x in re.split(r"[.!?]+", text) if x.strip()])
    normalize = lambda v: re.sub(
        r"[^a-z0-9]+", " ", str(v or "").lower().replace("’", "").replace("'", "")
    ).strip()
    targets = [p for p in c.get("target_phrases") or [] if isinstance(p, str) and p.strip()]
    matched = [
        p
        for p in targets
        if normalize(p) and " " + normalize(p) + " " in " " + normalize(text) + " "
    ]
    completed = bool(
        words > 0
        and words >= min_words
        and sentences >= min_sentences
        and len(checked) >= minimum
        and (mode != "guided" or not targets or matched)
    )
    return {
        "completed": completed,
        "word_count": words,
        "sentence_count": sentences,
        "checked_count": len(checked),
        "checklist_min": minimum,
        "response_text": text,
        "checked_items": list(checked),
        "matched_target_phrases": matched,
    }


def persist(lesson, progress, grade, feedback, assessment, completed, sealed, passing):
    """Commit progress, attempt, diagnostics and repeat receipt atomically."""
    from datetime import datetime, UTC
    from flask_login import current_user
    from app.utils.db import db
    from app.curriculum.models import LessonProgress, LessonAttempt, save_writing_attempt
    from app.curriculum.services.progress_service import _invalidate_user_progress_cache
    from app.daily_plan.linear.xp import (
        maybe_award_curriculum_xp,
        maybe_award_listening_xp,
        maybe_award_writing_xp,
    )
    from app.curriculum.listening_service import log_listening_attempt, log_pronunciation_attempt
    from app.curriculum.grading import check_final_test_attempts_exhausted
    from app.curriculum.routes.lessons import (
        _count_writing_attempts_today,
        _count_pronunciation_attempts_today,
        WRITING_DAILY_LIMIT,
        PRONUNCIATION_DAILY_LIMIT,
    )

    if lesson.type == "final_test" and check_final_test_attempts_exhausted(
        current_user.id, lesson.id, db_session=db
    ):
        _error("rate_limit_exceeded", 429)
    telemetry = grade.pop("_telemetry", {})
    if (
        telemetry.get("writing_text")
        and _count_writing_attempts_today(current_user.id) >= WRITING_DAILY_LIMIT
    ):
        _error("rate_limit_exceeded", 429)
    if (
        telemetry.get("pronunciation")
        and _count_pronunciation_attempts_today(current_user.id) + len(telemetry["pronunciation"])
        > PRONUNCIATION_DAILY_LIMIT
    ):
        _error("rate_limit_exceeded", 429)
    now = datetime.now(UTC)
    score = grade.get("score")
    if progress is None:
        progress = LessonProgress(
            user_id=current_user.id,
            lesson_id=lesson.id,
            status="in_progress",
            started_at=datetime.fromisoformat(sealed["started_at"]),
        )
        db.session.add(progress)
    if score is not None:
        progress.record_score(float(score))
    if completed:
        progress.status = "completed"
        if not progress.completed_at:
            progress.completed_at = now
    elif progress.status != "completed":
        progress.status = "in_progress"
    progress.last_activity = now
    response = {
        "success": True,
        "lesson_id": lesson.id,
        "score": score,
        "passed": bool(grade["passed"]),
        "completed": bool(completed),
        "assessment": assessment,
        "correct_count": sum(f["correct"] for f in feedback),
        "total_count": len(feedback),
        "feedback": feedback,
    }
    if grade.get("total_items") is not None and lesson.type in (
        "dictation",
        "matching",
        "collocation_matching",
    ):
        response.update(
            units_correct=grade.get("correct_items", 0),
            units_total=grade["total_items"],
            unit_label="Слов" if lesson.type == "dictation" else "Пар",
        )
    progress.data = {
        **grade,
        "_native_submission": {"nonce": sealed["nonce"], "response": response},
    }
    if telemetry.get("writing_checklist"):
        progress.data.update(telemetry["writing_checklist"])
    db.session.flush()
    if score is not None:
        attempt = LessonAttempt.create_attempt(current_user.id, lesson.id, progress.id)
        attempt.started_at = datetime.fromisoformat(sealed["started_at"])
        attempt.completed_at = now
        attempt.score = score
        attempt.passed = bool(grade["passed"])
        attempt.correct_answers = grade.get("correct_answers", grade.get("correct_items", 0))
        attempt.total_questions = grade.get(
            "total_questions", grade.get("total_items", len(feedback))
        )
        attempt.mistakes = [
            {"question": f["prompt"], "answer": f["answer"]} for f in feedback if not f["correct"]
        ]
    if telemetry.get("writing_text"):
        grammar_check = None
        if lesson.type == "writing_prompt":
            from app.utils.languagetool import check_text

            grammar_check = check_text(telemetry["writing_text"])
        save_writing_attempt(
            current_user.id,
            lesson.id,
            telemetry["writing_text"],
            bool(completed),
            db,
            grammar_check=grammar_check,
        )
    if telemetry.get("listening"):
        # Legacy self-assessed listening logs completion, not an exam score.
        log_listening_attempt(
            current_user.id, lesson.id, score if score is not None else 100.0, 0, db
        )
    for attempt in telemetry.get("pronunciation") or []:
        log_pronunciation_attempt(
            current_user.id, attempt["word"], attempt["recognized"], attempt["matched"], db
        )
    if lesson.type in QUIZZES | {"grammar"}:
        from app.daily_plan.linear.errors import log_quiz_errors_from_result

        log_quiz_errors_from_result(
            current_user.id,
            lesson.id,
            rows_for(lesson),
            grade,
            db,
            source="grammar" if lesson.type == "grammar" else "quiz",
        )
    if completed:
        maybe_award_curriculum_xp(current_user.id, lesson, db_session=db, score=score)
        if telemetry.get("listening"):
            maybe_award_listening_xp(
                current_user.id,
                lesson.id,
                score=score if score is not None else 100.0,
                db_session=db,
            )
        if telemetry.get("writing_text"):
            maybe_award_writing_xp(current_user.id, lesson.id, db_session=db)
    db.session.flush()
    if completed:
        from app.daily_plan.challenge import maybe_auto_complete_challenge

        maybe_auto_complete_challenge(
            current_user.id,
            lesson.id,
            bool(grade["passed"]),
            score,
            max(0, int((now - datetime.fromisoformat(sealed["started_at"])).total_seconds())),
            db,
        )
    db.session.commit()
    _invalidate_user_progress_cache(current_user.id)
    return response
