"""Tests for audit_dialogue_completion_quizzes.py and audit_ordering_quizzes.py.

Covers:
- hint detection and derivation
- correct-in-options check
- duplicate word detection in ordering exercises
- correct-constructible check for ordering exercises
- patch logic for dialogue_completion (hint filling)
- format_markdown output shape
- --no-db CLI mode
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from audit_dialogue_completion_quizzes import (
    ExerciseAudit as DCExerciseAudit,
    LessonAudit as DCLessonAudit,
    _correct_in_options,
    _derive_hints,
    _patch_content,
    audit_content as dc_audit_content,
    format_markdown as dc_format_markdown,
    main as dc_main,
)
from audit_ordering_quizzes import (
    ExerciseAudit as OQExerciseAudit,
    LessonAudit as OQLessonAudit,
    _check_correct_constructible,
    _check_no_duplicates,
    audit_content as oq_audit_content,
    format_markdown as oq_format_markdown,
    main as oq_main,
)


# ===========================================================================
# dialogue_completion_quiz audit
# ===========================================================================

class TestCorrectInOptions:
    def test_exact_match(self):
        assert _correct_in_options("Nice to meet you!", ["Hi", "Nice to meet you!"])

    def test_case_insensitive(self):
        assert _correct_in_options("HELLO", ["hello", "bye"])

    def test_strips_whitespace(self):
        assert _correct_in_options("  I'm fine  ", ["I'm fine"])

    def test_no_match(self):
        assert not _correct_in_options("Not here", ["Option A", "Option B"])

    def test_empty_options(self):
        assert not _correct_in_options("Something", [])

    def test_empty_correct(self):
        assert not _correct_in_options("", ["Option A"])


class TestDeriveHints:
    def test_uses_existing_hints(self):
        ex = {"hints": ["Подсказка"], "explanation": "Другой текст"}
        result = _derive_hints(ex)
        assert result == ["Подсказка"]

    def test_uses_existing_hint_singular(self):
        ex = {"hint": ["chip1"]}
        result = _derive_hints(ex)
        assert result == ["chip1"]

    def test_derives_from_explanation(self):
        ex = {"explanation": "Отвечаем на приветствие. Используйте 'Nice to meet you'."}
        result = _derive_hints(ex)
        assert len(result) == 1
        assert "Отвечаем на приветствие" in result[0]

    def test_no_hints_no_explanation(self):
        ex = {"options": ["A", "B"], "correct": "A"}
        result = _derive_hints(ex)
        assert result == []

    def test_long_explanation_truncated_to_120(self):
        ex = {"explanation": "A" * 200}
        result = _derive_hints(ex)
        assert len(result) == 1
        assert len(result[0]) <= 120

    def test_empty_explanation_gives_empty(self):
        ex = {"explanation": ""}
        result = _derive_hints(ex)
        assert result == []


class TestAuditContent:
    def _make_exercise(self, correct="Hello", options=None, hints=None, explanation=None):
        ex = {"type": "dialogue_completion", "correct": correct, "options": options or ["Hello", "Bye"]}
        if hints is not None:
            ex["hints"] = hints
        if explanation is not None:
            ex["explanation"] = explanation
        return ex

    def test_exercise_with_hints_ok(self):
        content = {"exercises": [self._make_exercise(hints=["Подсказка"])]}
        audit = dc_audit_content(1, "L1", "M1", "A1", content)
        assert len(audit.exercises) == 1
        assert audit.exercises[0].has_hints is True
        assert audit.exercises[0].correct_in_options is True
        assert audit.ok

    def test_exercise_missing_hints_flagged(self):
        content = {"exercises": [self._make_exercise()]}
        audit = dc_audit_content(1, "L1", "M1", "A1", content)
        assert audit.exercises[0].has_hints is False
        assert audit.exercises_missing_hints == 1
        assert not audit.ok

    def test_correct_not_in_options(self):
        content = {"exercises": [self._make_exercise(correct="Unknown", options=["A", "B"])]}
        audit = dc_audit_content(1, "L1", "M1", "A1", content)
        assert audit.exercises[0].correct_in_options is False
        assert audit.exercises_wrong_correct == 1

    def test_skips_non_dialogue_type(self):
        content = {"exercises": [{"type": "multiple_choice", "correct": "X", "options": ["X"]}]}
        audit = dc_audit_content(1, "L1", "M1", "A1", content)
        assert len(audit.exercises) == 0

    def test_empty_content(self):
        audit = dc_audit_content(1, "L1", "M1", "A1", {})
        assert len(audit.exercises) == 0
        assert audit.ok

    def test_questions_key_alias(self):
        ex = {"type": "dialogue_completion", "correct": "Hi", "options": ["Hi", "Bye"]}
        content = {"questions": [ex]}
        audit = dc_audit_content(1, "L1", "M1", "A1", content)
        assert len(audit.exercises) == 1


class TestPatchContent:
    def test_adds_hints_from_explanation(self):
        content = {
            "exercises": [
                {
                    "type": "dialogue_completion",
                    "correct": "Hi",
                    "options": ["Hi", "Bye"],
                    "explanation": "Это приветствие по-английски.",
                }
            ]
        }
        patched, applied = _patch_content(content)
        assert applied == 1
        assert patched["exercises"][0]["hints"] == ["Это приветствие по-английски"]

    def test_skips_if_hints_already_present(self):
        content = {
            "exercises": [
                {
                    "type": "dialogue_completion",
                    "correct": "Hi",
                    "options": ["Hi"],
                    "hints": ["Existing chip"],
                    "explanation": "Другой текст.",
                }
            ]
        }
        _, applied = _patch_content(content)
        assert applied == 0

    def test_no_explanation_no_patch(self):
        content = {
            "exercises": [{"type": "dialogue_completion", "correct": "Hi", "options": ["Hi"]}]
        }
        _, applied = _patch_content(content)
        assert applied == 0

    def test_original_content_not_mutated(self):
        content = {
            "exercises": [
                {
                    "type": "dialogue_completion",
                    "correct": "Hi",
                    "options": ["Hi"],
                    "explanation": "Пояснение",
                }
            ]
        }
        original_str = str(content)
        _patch_content(content)
        assert str(content) == original_str

    def test_idempotent_second_run(self):
        content = {
            "exercises": [
                {
                    "type": "dialogue_completion",
                    "correct": "Hi",
                    "options": ["Hi"],
                    "explanation": "Пояснение",
                }
            ]
        }
        patched, applied1 = _patch_content(content)
        _, applied2 = _patch_content(patched)
        assert applied2 == 0


class TestDCFormatMarkdown:
    def test_all_ok(self):
        audit = DCLessonAudit(1, "L1", "M1", "A1")
        audit.exercises.append(
            DCExerciseAudit(0, has_hints=True, correct_in_options=True, correct="Hi", options=["Hi"], hints=["Чип"])
        )
        md = dc_format_markdown([audit])
        assert "Lessons with issues: **0**" in md

    def test_issues_shown(self):
        audit = DCLessonAudit(1, "L1", "M1", "A1")
        audit.exercises.append(
            DCExerciseAudit(0, has_hints=False, correct_in_options=False, correct="X", options=["A"], hints=[])
        )
        md = dc_format_markdown([audit])
        assert "Exercises with duplicate" not in md
        assert "correct answer not in options" in md.lower() or "Exercises where correct" in md

    def test_changed_section_shown(self):
        md = dc_format_markdown([], changed=[(1, "L1", 3)])
        assert "Patches applied" in md


class TestDCMain:
    def test_no_db_mode_exits_zero(self):
        result = dc_main(["--no-db"])
        assert result == 0


# ===========================================================================
# ordering_quiz audit
# ===========================================================================

class TestCheckNoDuplicates:
    def test_unique_words_ok(self):
        ok, dups = _check_no_duplicates(["I", "am", "happy"])
        assert ok is True
        assert dups == []

    def test_duplicate_detected(self):
        ok, dups = _check_no_duplicates(["I", "I", "am"])
        assert ok is False
        assert "I" in dups

    def test_empty_list_ok(self):
        ok, dups = _check_no_duplicates([])
        assert ok is True
        assert dups == []

    def test_single_item_ok(self):
        ok, dups = _check_no_duplicates(["Hello"])
        assert ok is True

    def test_multiple_duplicates(self):
        ok, dups = _check_no_duplicates(["a", "a", "b", "b"])
        assert ok is False
        assert len(dups) == 2


class TestCheckCorrectConstructible:
    def test_exact_match(self):
        assert _check_correct_constructible(["I", "am", "happy"], "I am happy")

    def test_different_order_ok(self):
        assert _check_correct_constructible(["happy", "I", "am"], "I am happy")

    def test_extra_word_fails(self):
        assert not _check_correct_constructible(["I", "am"], "I am happy")

    def test_missing_word_fails(self):
        assert not _check_correct_constructible(["I", "am", "happy", "very"], "I am happy")

    def test_punctuation_as_separate_token(self):
        assert _check_correct_constructible(["Hello", ",", "world", "!"], "Hello , world !")

    def test_empty_words(self):
        assert not _check_correct_constructible([], "Something")

    def test_empty_correct(self):
        assert not _check_correct_constructible(["I", "am"], "")

    def test_question_mark_token(self):
        assert _check_correct_constructible(
            ["Where", "you", "from", "are", "?"],
            "Where are you from ?"
        )


class TestOQAuditContent:
    def _make_exercise(self, words, correct, ex_type="ordering"):
        return {"type": ex_type, "words": words, "correct": correct}

    def test_clean_exercise(self):
        content = {"exercises": [self._make_exercise(["I", "am", "happy"], "I am happy")]}
        audit = oq_audit_content(1, "L1", "M1", "A1", content)
        assert len(audit.exercises) == 1
        assert audit.exercises[0].no_duplicate_words is True
        assert audit.exercises[0].correct_constructible is True
        assert audit.ok

    def test_duplicate_words_flagged(self):
        content = {"exercises": [self._make_exercise(["I", "I", "am"], "I am")]}
        audit = oq_audit_content(1, "L1", "M1", "A1", content)
        assert audit.exercises[0].no_duplicate_words is False
        assert audit.exercises_with_duplicates == 1

    def test_not_constructible_flagged(self):
        content = {"exercises": [self._make_exercise(["I", "am"], "I am very happy")]}
        audit = oq_audit_content(1, "L1", "M1", "A1", content)
        assert audit.exercises[0].correct_constructible is False

    def test_reorder_type_accepted(self):
        content = {"exercises": [self._make_exercise(["Go", "I", "will"], "I will Go", "reorder")]}
        audit = oq_audit_content(1, "L1", "M1", "A1", content)
        assert len(audit.exercises) == 1

    def test_correct_answer_key_alias(self):
        ex = {"type": "ordering", "words": ["I", "am"], "correct_answer": "I am"}
        content = {"exercises": [ex]}
        audit = oq_audit_content(1, "L1", "M1", "A1", content)
        assert audit.exercises[0].correct_constructible is True

    def test_empty_content(self):
        audit = oq_audit_content(1, "L1", "M1", "A1", {})
        assert len(audit.exercises) == 0
        assert audit.ok

    def test_multiple_exercises(self):
        content = {
            "exercises": [
                self._make_exercise(["I", "am"], "I am"),
                self._make_exercise(["You", "are"], "You are"),
            ]
        }
        audit = oq_audit_content(1, "L1", "M1", "A1", content)
        assert len(audit.exercises) == 2
        assert audit.ok

    def test_questions_key_alias(self):
        ex = {"type": "ordering", "words": ["Go", "I"], "correct": "I Go"}
        content = {"questions": [ex]}
        audit = oq_audit_content(1, "L1", "M1", "A1", content)
        assert len(audit.exercises) == 1


class TestOQFormatMarkdown:
    def test_all_ok_message(self):
        audit = OQLessonAudit(1, "L1", "M1", "A1")
        audit.exercises.append(
            OQExerciseAudit(0, True, True, ["I", "am"], "I am", [])
        )
        md = oq_format_markdown([audit])
        assert "All ordering_quiz exercises pass" in md

    def test_issues_reported(self):
        audit = OQLessonAudit(1, "L1", "M1", "A1")
        audit.exercises.append(
            OQExerciseAudit(0, False, True, ["I", "I"], "I", ["I"])
        )
        md = oq_format_markdown([audit])
        assert "duplicate" in md.lower()

    def test_not_constructible_reported(self):
        audit = OQLessonAudit(1, "L1", "M1", "A1")
        audit.exercises.append(
            OQExerciseAudit(0, True, False, ["I", "am"], "I am very", [])
        )
        md = oq_format_markdown([audit])
        assert "constructible" in md.lower()


class TestOQMain:
    def test_no_db_mode_exits_zero(self):
        result = oq_main(["--no-db"])
        assert result == 0
