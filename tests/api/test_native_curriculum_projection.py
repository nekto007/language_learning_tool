# ruff: noqa: RUF001
"""Existing mobile input types preserve task context without leaking references.

Pure projection and real shared graders only: no app startup, database or network.
"""

from collections import Counter
from copy import deepcopy
import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.native_content import _question, check_course_answer, extras, grade, project
from app.api.native_lessons import NativeLessonError


def lesson(kind, content):
    return SimpleNamespace(
        id=37,
        type=kind,
        title="Authored lesson",
        content=deepcopy(content),
        module=SimpleNamespace(level=SimpleNamespace(code="B2")),
    )


def correct_choice(questions, labels):
    return {
        question["id"]: next(option["value"] for option in question["options"] if option["label"] == label)
        for question, label in zip(questions, labels, strict=True)
    }


def test_dialogue_list_preserves_speakers_partial_blank_and_authored_context():
    source = {
        "exercises": [
            {
                "type": "dialogue_completion",
                "context": "<p>Уточнение привычки</p>",
                "dialogue": [
                    {
                        "speaker": "<b>Alex</b>",
                        "text": "Do you drink coffee?",
                        "answer": "private-line-answer",
                        "explanation": "private-line-note",
                    },
                    {"speaker": "Sam", "text": "Yes, I ___ drink coffee.", "blank": True},
                ],
                "options": ["usually", "used"],
                "correct": "usually",
                "explanation": "private-after-answer",
            }
        ]
    }
    value = lesson("dialogue_completion_quiz", source)
    [question] = project(value)
    assert question["prompt"] == "Alex: Do you drink coffee?\nSam: Yes, I ___ drink coffee."
    assert question["context"] == "Уточнение привычки"
    assert question["input"] == "choice"
    encoded = json.dumps(question)
    assert not any(secret in encoded for secret in ["private-line-answer", "private-line-note", "private-after-answer"])
    result, _, assessment, completed = grade(value, [question], correct_choice([question], ["usually"]), 80)
    assert result["score"] == 100 and assessment == "graded" and completed
    assert value.content == source


def test_dialogue_explicit_blank_masks_filled_text_but_preserves_other_turns():
    value = lesson(
        "dialogue_completion_quiz",
        {
            "exercises": [
                {
                    "type": "dialogue_completion",
                    "dialogue": [
                        "A: How are you?",
                        {
                            "speaker": "B",
                            "text": "private-filled-reference",
                            "blank": True,
                            "transcript": "private-transcript",
                        },
                    ],
                    "options": ["Fine, thanks.", "Tomorrow."],
                    "correct": "Fine, thanks.",
                }
            ]
        },
    )
    [question] = project(value)
    assert question["prompt"] == "A: How are you?\nB: ___"
    assert "private-filled-reference" not in json.dumps(question)
    assert "private-transcript" not in json.dumps(question)


def test_legacy_string_dialogue_and_final_section_still_use_existing_choice_grader():
    value = lesson(
        "final_test",
        {
            "sections": [
                {
                    "title": "Диалог",
                    "exercises": [
                        {
                            "type": "dialogue_completion",
                            "dialogue": "A: Where is she?\nB: ___",
                            "options": ["At home.", "Yesterday."],
                            "correct": "At home.",
                        }
                    ],
                }
            ]
        },
    )
    questions = project(value)
    assert questions[0]["prompt"] == "A: Where is she?\nB: ___"
    assert questions[0]["section"] == "Диалог"
    result, _, _, completed = grade(value, questions, correct_choice(questions, ["At home."]), 80)
    assert result["score"] == 100 and completed


@pytest.mark.parametrize(
    ("prefix", "suffix", "context", "expected"),
    [
        ("I", "at six every morning.", "vocab use", "I ___ at six every morning."),
        (
            "",
            ", she visits galleries every week.",
            "Перепишите, используя причастный оборот: She loves art, so she visits galleries every week.",
            "___, she visits galleries every week.",
        ),
        ("I ___", "at six.", "Подберите глагол.", "I ___ at six."),
        ("After breakfast, I", "", "Продолжите предложение.", "After breakfast, I ___"),
    ],
)
def test_sentence_completion_preserves_prefix_blank_suffix_context_and_hint(prefix, suffix, context, expected):
    source = {
        "items": [
            {
                "prompt": prefix,
                "answer": "wake up",
                "prompt_after": suffix,
                "context": context,
                "hint": "w••• u•",
                "acceptable_answers": ["get up"],
                "explanation": "private-answer-explanation",
            }
        ]
    }
    value = lesson("sentence_completion", source)
    [question] = project(value)
    assert question["prompt"] == expected
    assert question["prompt"].count("___") == 1
    assert "Подсказка: w••• u•" in question["instruction"]
    if context == "vocab use":
        assert "context" not in question
    else:
        assert question["context"] == context
    encoded = json.dumps(question, ensure_ascii=False)
    assert "private-answer-explanation" not in encoded and "get up" not in encoded and "wake up" not in encoded
    for answer in ["wake up", "get up"]:
        result, _, assessment, completed = grade(value, [question], {"0": answer}, 80)
        assert result["score"] == 100 and assessment == "graded" and completed
    assert value.content == source


def test_sentence_without_any_authored_task_is_still_rejected():
    with pytest.raises(NativeLessonError) as error:
        project(lesson("sentence_completion", {"items": [{"answer": "private-key"}]}))
    assert error.value.code == "unsupported_lesson" and error.value.status == 422


def test_guided_translation_wordbank_is_visible_deterministic_and_keeps_chunks_duplicates():
    source = {
        "mode": "guided",
        "items": [
            {
                "russian": "У меня есть книга и карта Нью-Йорка.",
                "english": "I have a book and a New York map.",
                "hint_words": ["I", "have", "a", "book", "and", "a", "New York", "map."],
                "alternatives": ["private-unrelated-reference"],
            }
        ],
    }
    value = lesson("translation", source)
    [question] = project(value)
    assert question["prompt"] == "У меня есть книга и карта Нью-Йорка."
    bank = question["instruction"].split("Слова для перевода: ", 1)[1].split(" · ")
    assert Counter(bank) == Counter(source["items"][0]["hint_words"])
    assert "New York" in bank and bank.count("a") == 2
    assert project(value) == [question]
    assert "private-unrelated-reference" not in json.dumps(question)
    assert source["items"][0]["english"] not in question["instruction"]
    result, _, assessment, completed = grade(value, [question], {"0": source["items"][0]["english"]}, 80)
    assert result["score"] == 100 and assessment == "graded" and completed
    assert value.content == source


def test_open_translation_does_not_synthesize_a_wordbank_from_private_english():
    value = lesson(
        "translation",
        {
            "mode": "open",
            "items": [{"russian": "Я дома.", "english": "private-English-reference", "hint_words": ["private-bank"]}],
        },
    )
    [question] = project(value)
    assert question["input"] == "translation_review"
    assert "private" not in json.dumps(question)


def test_listening_choice_never_uses_transcript_fields_as_visible_prompt():
    transcript = "private-listening-transcript-unique-sentinel"
    row = {
        "type": "listening_choice",
        "question": "What did the speaker order?",
        "prompt": "Choose what you heard.",
        "text": transcript,
        "sentence": transcript,
        "dialogue": [{"speaker": "A", "text": transcript}],
        "statement": transcript,
        "audio_text": transcript,
        "transcript": transcript,
        "audio": "[sound:lesson.mp3]",
        "options": ["Coffee.", "Tea."],
        "correct": "Coffee.",
    }
    value = lesson("listening_quiz", {"questions": [row], "text": transcript, "transcript": transcript})
    [question] = project(value)
    assert question["prompt"] == "What did the speaker order?\nChoose what you heard."
    assert question["audio_url"] == "/static/audio/lesson.mp3"
    assert transcript not in json.dumps({"question": question, "extras": extras(value)})
    result, _, _, completed = grade(value, [question], correct_choice([question], ["Coffee."]), 80)
    assert result["score"] == 100 and completed
    reading = _question(lesson("reading", {}), {**row, "type": "reading_comprehension"}, 0)
    assert transcript in reading["prompt"]  # Explicit reading material stays readable.


@pytest.mark.parametrize("level", ["A1", "A2"])
@pytest.mark.parametrize(("authored", "expected"), [
    ({"question_ru": "Что слышно?"}, None),
    ({"question_ru": "Что слышно"}, "Что слышно"),
    ({"question_ru": "Что слышно?", "prompt": "Choose one word."}, "Что слышно?"),
    ({}, ""),
])
def test_listening_translation_compares_exactly_to_the_final_prompt(
    level: str, authored: dict[str, str], expected: str | None,
) -> None:
    row = {
        "type": "listening_choice", "question": "<strong>Что слышно?</strong>",
        "audio": "[sound:synthetic.mp3]", "audio_text": "bus", "audio_translation": "автобус",
        "options": ["bus", "train"], "correct": "bus",
        **authored,
    }
    value = lesson("listening_quiz", {"exercises": [row]})
    value.module.level.code = level
    [question] = project(value)
    assert question["prompt"] == "\n".join(filter(None, ("Что слышно?", authored.get("prompt"))))
    assert question["translation"] == expected
    assert question["audio_url"] == "/static/audio/synthetic.mp3"
    assert {item["value"]: item["label"] for item in question["options"]} == {"0": "bus", "1": "train"}
    assert check_course_answer(value, question, "0")["correct"] is True
    assert check_course_answer(value, question, "1")["correct"] is False
    assert value.content["exercises"] == [row]


@pytest.mark.parametrize(("lesson_type", "row_type"), [
    ("listening_quiz", "multiple_choice"), ("listening_immersion", "listening_choice"),
])
def test_equal_translation_kept_outside_the_target_listening_format(lesson_type: str, row_type: str) -> None:
    row: dict[str, Any] = {
        "type": row_type, "question": "Что слышно?", "question_ru": "Что слышно?",
        "options": ["bus", "train"], "correct": "bus",
    }
    value = lesson(lesson_type, {"questions": [row]})
    value.module.level.code = "A2"
    assert _question(value, row, 0)["translation"] == "Что слышно?"


@pytest.mark.parametrize("rows_key", ["questions", "exercises", "comprehension_questions"])
def test_objective_listening_theory_hides_reference_for_every_supported_question_container(rows_key):
    transcript = "private-recording-transcript-sentinel"
    value = lesson(
        "listening_immersion",
        {
            "text": transcript,
            "transcript": transcript,
            rows_key: [
                {
                    "type": "multiple_choice",
                    "question": "What was ordered?",
                    "options": ["Coffee.", "Tea."],
                    "correct": "Coffee.",
                }
            ],
        },
    )
    assert extras(value)["theory"] == []
    assert transcript not in json.dumps(project(value))


def test_self_assessed_recording_exposes_only_explicit_study_text_and_no_accuracy():
    value = lesson(
        "listening_immersion",
        {
            "text": "Study reference: a conversation in a café.",
            "transcript": "private-other-transcript",
            "audio": "[sound:lesson.mp3]",
        },
    )
    projected = extras(value)
    assert projected["assessment"] == "self_assessed"
    assert any(block["title"] == "Текст записи" and block["body"] == value.content["text"] for block in projected["theory"])
    assert "private-other-transcript" not in json.dumps(projected)
    questions = project(value)
    result, _, assessment, completed = grade(value, questions, {"0": "confirmed"}, 80)
    assert result["score"] is None and assessment == "self_assessed" and completed
