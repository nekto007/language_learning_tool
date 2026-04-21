import json
import re
from collections import defaultdict
from pathlib import Path

import pytest


MODULE_DIR = Path(__file__).resolve().parents[1] / "module_completed" / "fixed"

LEVEL_TARGETS = {
    "A1": {"vocab": 15, "exercises": 60, "reading_words": 90, "listening_words": 90, "dialogues": 3},
    "A2": {"vocab": 18, "exercises": 65, "reading_words": 130, "listening_words": 120, "dialogues": 4},
    "B1": {"vocab": 20, "exercises": 70, "reading_words": 220, "listening_words": 180, "dialogues": 5},
    "B2": {"vocab": 24, "exercises": 80, "reading_words": 320, "listening_words": 250, "dialogues": 6},
    "C1": {"vocab": 28, "exercises": 90, "reading_words": 420, "listening_words": 330, "dialogues": 7},
}

EXPECTED_LESSON_TYPES = [
    "vocabulary",
    "flashcards",
    "grammar",
    "quiz",
    "reading",
    "listening_quiz",
    "dialogue_completion_quiz",
    "ordering_quiz",
    "flashcards",
    "translation_quiz",
    "listening_immersion",
    "final_test",
]


def module_files():
    files = sorted(MODULE_DIR.glob("module_*.json"))
    if not files:
        pytest.skip(f"No module JSON files found in {MODULE_DIR}")
    return files


def word_count(value):
    return len(re.findall(r"[A-Za-z']+", str(value)))


def english_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if "lines" in value:
            return " ".join(str(line.get("text", "")) for line in value["lines"] if isinstance(line, dict))
        if "text" in value:
            return english_text(value["text"])
        return ""
    if isinstance(value, list):
        return " ".join(english_text(item) for item in value)
    return ""


def iter_exercises(node):
    if isinstance(node, dict):
        if "type" in node and any(key in node for key in ("question", "correct", "options", "words", "dialogue")):
            yield node
        for value in node.values():
            yield from iter_exercises(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_exercises(item)


def module_metrics(module):
    metrics = {"vocab": 0, "exercises": 0, "reading_words": 0, "listening_words": 0, "dialogues": 0}
    metrics["vocab"] = len(module["lessons"][0]["content"].get("vocabulary", []))

    for lesson in module["lessons"]:
        content = lesson.get("content", {})
        metrics["exercises"] += len(content.get("exercises", []))
        metrics["exercises"] += sum(len(section.get("exercises", [])) for section in content.get("test_sections", []))

        if lesson["type"] == "reading":
            metrics["reading_words"] = word_count(english_text(content.get("text", "")))
        if lesson["type"] == "listening_immersion":
            metrics["listening_words"] = word_count(english_text(content.get("text", "")))

        metrics["dialogues"] += sum(1 for exercise in iter_exercises(content) if exercise.get("type") == "dialogue_completion")

    return metrics


def normalize_choice(value):
    return str(value).lower().strip()


def load_modules():
    modules = []
    for path in module_files():
        with path.open(encoding="utf-8") as handle:
            modules.append((path, json.load(handle)["module"]))
    return modules


def test_module_lesson_structure_is_stable():
    for path, module in load_modules():
        assert len(module["lessons"]) == 12, path
        assert [lesson["type"] for lesson in module["lessons"]] == EXPECTED_LESSON_TYPES, path
        assert [lesson["order"] for lesson in module["lessons"]] == list(range(1, 13)), path


def test_module_level_quality_targets_are_met_and_progressive():
    by_level = defaultdict(list)

    for path, module in load_modules():
        level = module["level"]
        assert level in LEVEL_TARGETS, path
        metrics = module_metrics(module)
        by_level[level].append(metrics)
        for key, target in LEVEL_TARGETS[level].items():
            assert metrics[key] >= target, f"{path}: {key}={metrics[key]} < {target}"

    levels = [level for level in ("A1", "A2", "B1", "B2", "C1") if level in by_level]
    for previous, current in zip(levels, levels[1:]):
        prev_min = {key: min(metrics[key] for metrics in by_level[previous]) for key in LEVEL_TARGETS[previous]}
        curr_min = {key: min(metrics[key] for metrics in by_level[current]) for key in LEVEL_TARGETS[current]}
        for key in prev_min:
            assert curr_min[key] > prev_min[key], f"{key} does not increase from {previous} to {current}"


def test_open_answer_questions_have_acceptable_answers():
    for path, module in load_modules():
        for exercise in iter_exercises(module):
            if exercise.get("type") not in {"translation", "transformation"}:
                continue

            acceptable = exercise.get("acceptable_answers")
            assert isinstance(acceptable, list) and acceptable, f"{path}: missing acceptable_answers in {exercise}"
            assert exercise.get("correct") in acceptable, f"{path}: correct answer is not accepted in {exercise}"


def test_choice_correct_answers_are_present_in_options():
    choice_types = {"multiple_choice", "fill_blank", "listening_choice", "dialogue_completion", "reading_comprehension"}

    for path, module in load_modules():
        for exercise in iter_exercises(module):
            if exercise.get("type") not in choice_types or "options" not in exercise:
                continue

            options = [normalize_choice(option) for option in exercise["options"]]
            assert normalize_choice(exercise.get("correct")) in options, f"{path}: correct not in options for {exercise}"


def test_advanced_levels_have_contextual_examples():
    for path, module in load_modules():
        if module["level"] not in {"B1", "B2", "C1"}:
            continue

        short_examples = []
        minimum_words = 6 if module["level"] == "B1" else 7
        for item in module["lessons"][0]["content"].get("vocabulary", []):
            example = item.get("example", "")
            if word_count(example) < minimum_words:
                short_examples.append(example)

        assert not short_examples, f"{path}: short contextual examples: {short_examples[:5]}"


def test_no_generic_generator_placeholders_remain():
    banned_patterns = [
        r"Two people are discussing",
        r"No, details are never useful",
        r"I never listen to context",
        r"It has no evidence at all",
        r"Любой вывод об аспекте",
        r"Нам нужны надежные доказательства",
        r"Нужно объяснить и преимущества",
        r"Мы можем понятно объяснить",
        r"We need a clear ___",
        r"Which sentence clearly mentions",
        r"Which sentence is most suitable",
        r"Rewrite in a more formal style",
        r"Rewrite with greater nuance",
        r"A nuanced interpretation of",
        r"A balanced evaluation of",
        r"Дополнительный фрагмент аудирования",
        r"What are your plans for",
        r"Can you add a daily context",
        r"Why is .* difficult to evaluate",
        r"The term '",
        r"often shapes the wider debate",
        r"can reveal the underlying assumptions",
        r"helps frame a nuanced argument",
        r"\bA (ethical|institutional|underlying|evidential|analytical|unintended|reliable evidence|long-term implications)",
    ]
    combined = re.compile("|".join(banned_patterns), re.IGNORECASE)

    for path, module in load_modules():
        text = json.dumps(module, ensure_ascii=False)
        match = combined.search(text)
        assert match is None, f"{path}: generic generated text remains: {match.group(0)}"


def test_generated_content_is_not_repeated_verbatim():
    for path, module in load_modules():
        reading_blocks = []
        listening_blocks = []

        for lesson in module["lessons"]:
            content = lesson.get("content", {})
            if lesson["type"] == "reading":
                text = content.get("text", "")
                if isinstance(text, dict) and "lines" in text:
                    reading_blocks.extend(line.get("text", "") for line in text["lines"] if isinstance(line, dict))
                else:
                    reading_blocks.extend(block.strip() for block in english_text(text).split("\n\n") if block.strip())
            elif lesson["type"] == "listening_immersion":
                listening_blocks.extend(block.strip() for block in english_text(content.get("text", "")).split("\n") if block.strip())

        for blocks, label in ((reading_blocks, "reading"), (listening_blocks, "listening")):
            duplicates = {block for block in blocks if block and blocks.count(block) > 1}
            assert not duplicates, f"{path}: repeated {label} blocks: {list(duplicates)[:3]}"
