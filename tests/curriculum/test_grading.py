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
    grade_dictation,
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


class TestGradeDictation:
    def test_exact_match_scores_100(self):
        result = grade_dictation("The cat sat on the mat", "The cat sat on the mat")
        assert result["score"] == 100
        assert result["passed"] is True
        assert result["correct_words"] == 6
        assert result["total_words"] == 6

    def test_one_wrong_word_in_five_is_80_pass(self):
        result = grade_dictation("the cat sat on a", "the cat sat on the")
        assert result["score"] == 80
        assert result["passed"] is True
        assert result["correct_words"] == 4
        assert result["total_words"] == 5

    def test_three_wrong_words_in_five_is_40_fail(self):
        result = grade_dictation("dog runs up a hill", "the cat sat on the")
        assert result["score"] == 0
        assert result["passed"] is False

    def test_punctuation_ignored(self):
        result = grade_dictation("Hello, world! It's a test.", "Hello world it's a test")
        assert result["score"] == 100
        assert result["passed"] is True

    def test_apostrophes_preserved_in_contractions(self):
        result = grade_dictation("don't stop", "don't stop")
        assert result["score"] == 100

    def test_hint_chars_does_not_change_grading(self):
        # With hint_chars=3, client pre-fills first 3 chars; full words still compared
        result = grade_dictation("beautiful scenery", "beautiful scenery", hint_chars=3)
        assert result["score"] == 100
        assert result["passed"] is True

    def test_empty_transcript_returns_zero(self):
        result = grade_dictation("something", "")
        assert result["score"] == 0
        assert result["total_words"] == 0

    def test_user_has_fewer_words_than_transcript(self):
        result = grade_dictation("one two", "one two three four five")
        assert result["total_words"] == 5
        assert result["correct_words"] == 2

    def test_case_insensitive(self):
        result = grade_dictation("THE CAT SAT", "the cat sat")
        assert result["score"] == 100

    def test_three_wrong_in_five_explicit(self):
        result = grade_dictation("one wrong wrong wrong five", "one two three four five")
        assert result["correct_words"] == 2
        assert result["total_words"] == 5
        assert result["score"] == 40
        assert result["passed"] is False


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
