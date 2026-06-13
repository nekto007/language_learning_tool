"""Regression tests for grader robustness (audit 2026-06-13, E-031..E-036).

These cover the divergences between the hardened ``process_quiz_submission``
path and the final_test / grammar / matching graders:
- string-digit / option-text ``correct_answer`` in multiple_choice (E-031)
- string ``"true"`` ``correct_answer`` in true_false (E-032)
- {english,russian} / {word,translation} pair shapes in matching graders
  that previously raised KeyError -> 500 (E-033, E-035, E-036)
- final_test fill_in_blank/translation parity with quiz typo tolerance and
  list-shaped reorder ``correct_answer`` (E-034)
"""
from __future__ import annotations

import pytest

from app.curriculum.grading import (
    _coerce_bool,
    _coerce_to_index,
    _pair_left,
    _pair_right,
    process_final_test_submission,
    process_grammar_submission,
    process_matching_submission,
)


# --- helpers ---------------------------------------------------------------

def test_coerce_to_index_handles_all_shapes():
    opts = ["alpha", "beta", "gamma"]
    assert _coerce_to_index(1, opts) == 1
    assert _coerce_to_index("2", opts) == 2
    assert _coerce_to_index("beta", opts) == 1
    assert _coerce_to_index("BETA", opts) == 1  # case-insensitive
    assert _coerce_to_index("nope", opts) == -1
    assert _coerce_to_index(None, opts) == -1
    assert _coerce_to_index(True, opts) == -1  # bool is not an index


def test_coerce_bool_handles_strings_and_numbers():
    assert _coerce_bool(True) is True
    assert _coerce_bool("true") is True
    assert _coerce_bool("True") is True
    assert _coerce_bool("yes") is True
    assert _coerce_bool("1") is True
    assert _coerce_bool("false") is False
    assert _coerce_bool(0) is False
    assert _coerce_bool(None) is False


def test_pair_extractors_multi_shape():
    assert _pair_left({"left": "a", "right": "b"}) == "a"
    assert _pair_left({"english": "a", "russian": "b"}) == "a"
    assert _pair_left({"word": "a", "translation": "b"}) == "a"
    assert _pair_right({"english": "a", "russian": "b"}) == "b"
    assert _pair_left("not a dict") == ""


# --- final_test multiple_choice (E-031) -----------------------------------

def test_final_test_mc_string_correct_answer_passes():
    questions = [{"type": "multiple_choice", "answer": "2",
                  "options": ["a", "b", "c"]}]
    res = process_final_test_submission(questions, {"0": "2"})
    assert res["feedback"]["0"]["is_correct"] is True


def test_final_test_mc_text_answer_resolves_via_options():
    questions = [{"type": "multiple_choice", "answer": "beta",
                  "options": ["alpha", "beta", "gamma"]}]
    res = process_final_test_submission(questions, {"0": "1"})
    assert res["feedback"]["0"]["is_correct"] is True


def test_final_test_mc_unresolvable_correct_answer_is_wrong():
    # correct_answer can't be resolved -> must NOT pass (no -1 == -1 trap)
    questions = [{"type": "multiple_choice", "answer": "zzz",
                  "options": ["a", "b"]}]
    res = process_final_test_submission(questions, {"0": "9"})
    assert res["feedback"]["0"]["is_correct"] is False


# --- final_test true_false (E-032) ----------------------------------------

def test_final_test_true_false_string_answer():
    questions = [{"type": "true_false", "answer": "true"}]
    res = process_final_test_submission(questions, {"0": "true"})
    assert res["feedback"]["0"]["is_correct"] is True


# --- final_test matching (E-033) ------------------------------------------

def test_final_test_matching_english_russian_pairs_no_keyerror():
    questions = [{
        "type": "matching",
        "pairs": [{"english": "dog", "russian": "собака"},
                  {"english": "cat", "russian": "кошка"}],
    }]
    user = {"0": {"dog": "собака", "cat": "кошка"}}
    res = process_final_test_submission(questions, user)
    assert res["feedback"]["0"]["is_correct"] is True


# --- final_test fill_in_blank typo tolerance (E-034) ----------------------

def test_final_test_fill_in_blank_typo_tolerance():
    questions = [{"type": "fill_in_blank", "answer": "running"}]
    res = process_final_test_submission(questions, {"0": "runnig"})
    assert res["feedback"]["0"]["is_correct"] is True


def test_final_test_reorder_list_correct_answer_no_crash():
    # Before the fix, normalize_text(list) raised; now str() guards it and the
    # normalized token stream happens to match the user's sentence.
    questions = [{"type": "reorder", "answer": ["I", "am", "here"]}]
    res = process_final_test_submission(questions, {"0": "I am here"})
    assert res["feedback"]["0"]["is_correct"] is True


# --- grammar match (E-035) ------------------------------------------------

def test_grammar_match_english_russian_pairs_no_keyerror():
    exercises = [{
        "type": "match",
        "pairs": [{"english": "dog", "russian": "собака"},
                  {"english": "cat", "russian": "кошка"}],
    }]
    # user_matches maps left index -> right index; identity is correct here
    answers = {0: {"0": "0", "1": "1"}}
    res = process_grammar_submission(exercises, answers)
    assert res["correct_answers"] == 1


# --- standalone matching (E-036) ------------------------------------------

def test_process_matching_submission_word_translation_pairs():
    pairs = [{"word": "dog", "translation": "собака"},
             {"word": "cat", "translation": "кошка"}]
    user_matches = {"0": 0, "1": 1}
    res = process_matching_submission(pairs, user_matches)
    assert res["correct_matches"] == 2
