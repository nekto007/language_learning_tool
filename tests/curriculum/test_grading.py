"""Strict-grading tests for curriculum quiz answers.

Covers Task 1 of 2026-04-26-learning-quality-audit:
- fill_in_blank: exact-match (after normalization) with single-word
  Levenshtein ≤1 typo tolerance. Substring/overlap heuristics no longer
  credit wrong answers like "I have been waiting for hour" (missing 'an').
- matching: server-side pair validation. Legacy clients sending the
  sentinel ``'completed'`` without pairs are rejected.
"""
from __future__ import annotations

import pytest

from app.curriculum.grading import (
    _grade_matching_pairs,
    _levenshtein,
    _normalize_answer,
    _strict_text_match,
    process_quiz_submission,
)


def test_levenshtein_basic():
    assert _levenshtein("hello", "hello") == 0
    assert _levenshtein("hello", "helo") == 1
    assert _levenshtein("kitten", "sitting") == 3
    assert _levenshtein("", "abc") == 3
    assert _levenshtein("abc", "") == 3


def test_normalize_answer_strips_punctuation():
    assert _normalize_answer("  Hello, World! ") == "hello world"
    assert _normalize_answer(None) == ""


def test_strict_text_match_exact_and_typo():
    assert _strict_text_match("apple", ["apple"]) is True
    assert _strict_text_match("Apple ", ["apple"]) is True
    # Single-word typo within Levenshtein 1 → accepted.
    assert _strict_text_match("aple", ["apple"]) is True
    # Two edits → rejected.
    assert _strict_text_match("aple", ["banana"]) is False
    assert _strict_text_match("xyz", ["apple"]) is False


def test_strict_text_match_multiword_requires_exact():
    candidates = ["I have been waiting for an hour"]
    # Missing article — previously credited at 6/7 = 86% overlap, now rejected.
    assert _strict_text_match("I have been waiting for hour", candidates) is False
    # Wrong subject — previously credited, now rejected.
    assert _strict_text_match("you have been waiting for an hour", candidates) is False
    # Exact match (case/punctuation insensitive) accepted.
    assert _strict_text_match("i have been waiting for an hour.", candidates) is True


def test_strict_text_match_empty_user_answer():
    assert _strict_text_match("", ["apple"]) is False
    assert _strict_text_match("   ", ["apple"]) is False


def test_grade_matching_pairs_correct_order_independent():
    correct = [{"left": "cat", "right": "кот"}, {"left": "dog", "right": "пёс"}]
    user = [{"left": "dog", "right": "пёс"}, {"left": "cat", "right": "кот"}]
    assert _grade_matching_pairs(user, correct) is True


def test_grade_matching_pairs_swapped_rejected():
    correct = [{"left": "cat", "right": "кот"}, {"left": "dog", "right": "пёс"}]
    user = [{"left": "cat", "right": "пёс"}, {"left": "dog", "right": "кот"}]
    assert _grade_matching_pairs(user, correct) is False


def test_grade_matching_pairs_legacy_completed_rejected():
    correct = [{"left": "cat", "right": "кот"}]
    assert _grade_matching_pairs("completed", correct) is False
    assert _grade_matching_pairs(None, correct) is False
    assert _grade_matching_pairs([], correct) is False


def test_quiz_submission_fill_in_blank_strict():
    questions = [
        {
            "type": "fill_in_blank",
            "answer": "I have been waiting for an hour",
        }
    ]
    # Missing article → rejected.
    result = process_quiz_submission(questions, {0: "I have been waiting for hour"})
    assert result["correct_answers"] == 0
    # Exact (with punctuation differences) → accepted.
    result = process_quiz_submission(questions, {0: "i have been waiting for an hour."})
    assert result["correct_answers"] == 1


def test_quiz_submission_fill_in_blank_typo_tolerance_single_word():
    questions = [{"type": "fill_in_blank", "answer": "apple"}]
    result = process_quiz_submission(questions, {0: "aple"})
    assert result["correct_answers"] == 1
    result = process_quiz_submission(questions, {0: "banana"})
    assert result["correct_answers"] == 0


def test_quiz_submission_matching_legacy_completed_rejected():
    questions = [
        {
            "type": "matching",
            "pairs": [
                {"left": "cat", "right": "кот"},
                {"left": "dog", "right": "пёс"},
            ],
        }
    ]
    result = process_quiz_submission(questions, {0: "completed"})
    assert result["correct_answers"] == 0


def test_quiz_submission_matching_json_string_dict():
    """Frontend posts matching as JSON.stringify({left: right, ...})."""
    import json as _json
    questions = [
        {
            "type": "matching",
            "pairs": [
                {"left": "cat", "right": "кот"},
                {"left": "dog", "right": "пёс"},
            ],
        }
    ]
    payload = _json.dumps({"cat": "кот", "dog": "пёс"})
    result = process_quiz_submission(questions, {0: payload})
    assert result["correct_answers"] == 1

    bad_payload = _json.dumps({"cat": "пёс", "dog": "кот"})
    result = process_quiz_submission(questions, {0: bad_payload})
    assert result["correct_answers"] == 0


def test_quiz_submission_matching_with_pairs():
    questions = [
        {
            "type": "matching",
            "pairs": [
                {"left": "cat", "right": "кот"},
                {"left": "dog", "right": "пёс"},
            ],
        }
    ]
    user_pairs = [
        {"left": "cat", "right": "кот"},
        {"left": "dog", "right": "пёс"},
    ]
    result = process_quiz_submission(questions, {0: user_pairs})
    assert result["correct_answers"] == 1

    # Wrong pairing → rejected.
    bad_pairs = [
        {"left": "cat", "right": "пёс"},
        {"left": "dog", "right": "кот"},
    ]
    result = process_quiz_submission(questions, {0: bad_pairs})
    assert result["correct_answers"] == 0
