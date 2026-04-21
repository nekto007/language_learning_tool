import json
import re
from collections import Counter
from pathlib import Path

import pytest


EXTRA_DIR = Path(__file__).resolve().parents[1] / "grammar_exercises_extra"


def grammar_extra_files():
    files = sorted(EXTRA_DIR.glob("**/grammar_extra_*.json"))
    if not files:
        pytest.skip(f"No grammar extra JSON files found in {EXTRA_DIR}")
    return files


def load_files():
    for path in grammar_extra_files():
        with path.open(encoding="utf-8") as handle:
            yield path, json.load(handle)


def answer_tokens(value):
    return re.findall(
        r"[A-Za-zА-Яа-яЁё0-9]+(?:['’][A-Za-zА-Яа-яЁё0-9]+)?(?:-[A-Za-zА-Яа-яЁё0-9]+)*|[?.!,—-]",
        str(value),
    )


def word_count(value):
    return len(re.findall(r"[A-Za-z']+", str(value)))


def expected_difficulty(session_number):
    if session_number in {1, 2, 3}:
        return 1
    if session_number in {4, 5}:
        return 2
    return 3


def test_grammar_extra_structure_and_progression_are_stable():
    for path, data in load_files():
        assert len(data["sessions"]) == 8, path
        assert data["level"] in {"A1", "A2", "B1", "B2", "C1"}, path

        for session in data["sessions"]:
            exercises = session["exercises"]
            assert len(exercises) == 10, f"{path}: session {session['session_number']}"
            assert [exercise["order"] for exercise in exercises] == list(range(1, 11)), path

            difficulty = expected_difficulty(session["session_number"])
            for exercise in exercises:
                assert exercise["difficulty"] == difficulty, (
                    f"{path}: session {session['session_number']} order {exercise['order']}"
                )


def test_grammar_extra_answers_match_exercise_contracts():
    for path, data in load_files():
        for session in data["sessions"]:
            for exercise in session["exercises"]:
                content = exercise["content"]
                exercise_type = exercise["exercise_type"]

                if exercise_type == "multiple_choice":
                    assert content["correct_answer"] in content["options"], (
                        f"{path}: session {session['session_number']} order {exercise['order']}"
                    )

                if exercise_type == "translation":
                    assert content.get("alternatives"), (
                        f"{path}: translation without alternatives at session "
                        f"{session['session_number']} order {exercise['order']}"
                    )

                if exercise_type == "error_correction":
                    assert content["error_word"] in content["sentence"], (
                        f"{path}: error word is not present at session "
                        f"{session['session_number']} order {exercise['order']}"
                    )
                    assert content["correct_word"] in content.get("alternatives", []), (
                        f"{path}: corrected word is not accepted at session "
                        f"{session['session_number']} order {exercise['order']}"
                    )

                if exercise_type == "reorder":
                    assert Counter(token.lower() for token in answer_tokens(content["correct_answer"])) == Counter(
                        str(word).lower() for word in content["words"]
                    ), f"{path}: reorder words mismatch at session {session['session_number']} order {exercise['order']}"


def test_advanced_reorder_items_are_not_too_short():
    for path, data in load_files():
        if data["level"] not in {"B2", "C1"}:
            continue

        minimum_words = 6 if data["level"] == "B2" else 7
        for session in data["sessions"]:
            if expected_difficulty(session["session_number"]) < 3:
                continue
            for exercise in session["exercises"]:
                if exercise["exercise_type"] != "reorder":
                    continue
                answer = exercise["content"]["correct_answer"]
                assert word_count(answer) >= minimum_words, (
                    f"{path}: short advanced reorder at session "
                    f"{session['session_number']} order {exercise['order']}: {answer}"
                )


def test_no_generic_generator_placeholders_in_grammar_extra():
    banned = re.compile(
        r"Two people are discussing|No, details are never useful|Любой вывод об аспекте|"
        r"Нам нужны надежные доказательства|The term '|often shapes|can reveal the underlying|"
        r"Дополнительный фрагмент|This point is especially|example [0-9]+",
        re.IGNORECASE,
    )

    for path, data in load_files():
        text = json.dumps(data, ensure_ascii=False)
        match = banned.search(text)
        assert match is None, f"{path}: generic generated text remains: {match.group(0)}"
