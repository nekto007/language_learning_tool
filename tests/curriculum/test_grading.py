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
    grade_audio_fill_blank,
    grade_collocation_matching,
    grade_dictation,
    grade_sentence_completion,
    grade_sentence_correction_multi,
    grade_translation,
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

    def test_all_words_wrong_is_zero_fail(self):
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


class TestGradeTranslation:
    def test_exact_match_correct(self):
        result = grade_translation("I like apples", "I like apples")
        assert result["is_correct"] is True

    def test_exact_match_case_and_punctuation_ignored(self):
        result = grade_translation("i like apples.", "I like apples")
        assert result["is_correct"] is True

    def test_single_word_typo_1_accepted(self):
        result = grade_translation("aple", "apple")
        assert result["is_correct"] is True

    def test_single_word_typo_2_rejected(self):
        result = grade_translation("apl", "apple")
        assert result["is_correct"] is False

    def test_multiword_wrong_word_order_rejected(self):
        result = grade_translation("apples like I", "I like apples")
        assert result["is_correct"] is False

    def test_multiword_missing_word_rejected(self):
        result = grade_translation("I like", "I like apples")
        assert result["is_correct"] is False

    def test_multiword_exact_match_accepted(self):
        result = grade_translation("She goes to school every day", "She goes to school every day")
        assert result["is_correct"] is True

    def test_empty_user_answer_rejected(self):
        result = grade_translation("", "I like apples")
        assert result["is_correct"] is False

    def test_punctuation_in_correct_answer_ignored(self):
        result = grade_translation("hello world", "Hello, world!")
        assert result["is_correct"] is True

    def test_result_contains_expected_keys(self):
        result = grade_translation("test", "test")
        assert "is_correct" in result
        assert "user_answer" in result
        assert "correct_answer" in result


class TestTranslationValidator:
    def test_valid_translation_schema(self):
        from app.curriculum.validators import LessonContentValidator

        is_valid, err, _ = LessonContentValidator.validate(
            'translation', {'russian': 'Я люблю яблоки', 'english': 'I like apples'}
        )
        assert is_valid is True
        assert err is None

    def test_translation_with_hint_words(self):
        from app.curriculum.validators import LessonContentValidator

        is_valid, err, data = LessonContentValidator.validate(
            'translation',
            {'russian': 'Она идёт в школу', 'english': 'She goes to school', 'hint_words': ['She', 'goes']},
        )
        assert is_valid is True

    def test_missing_russian_fails(self):
        from marshmallow import ValidationError
        from app.curriculum.validators import LessonContentValidator

        try:
            LessonContentValidator.validate('translation', {'english': 'I like apples'})
            assert False, "Should have raised"
        except ValidationError:
            pass

    def test_missing_english_fails(self):
        from marshmallow import ValidationError
        from app.curriculum.validators import LessonContentValidator

        try:
            LessonContentValidator.validate('translation', {'russian': 'Я люблю яблоки'})
            assert False, "Should have raised"
        except ValidationError:
            pass


# ---------------------------------------------------------------------------
# Task 8 additions: unicode, empty answer, partial matching, None content fields
# ---------------------------------------------------------------------------

class TestUnicodeAndDiacritics:
    """fill-in-blank grading with unicode characters, diacritics, Cyrillic."""

    def test_cyrillic_exact_match(self):
        assert _strict_text_match("привет", ["привет"]) is True

    def test_cyrillic_case_insensitive(self):
        assert _strict_text_match("ПРИВЕТ", ["привет"]) is True

    def test_cyrillic_mismatch(self):
        assert _strict_text_match("привет", ["пока"]) is False

    def test_diacritic_exact_match(self):
        assert _strict_text_match("café", ["café"]) is True

    def test_diacritic_typo_tolerance(self):
        # "cafe" vs "café" — 1 substitution for the accented char
        assert _strict_text_match("cafe", ["café"]) is True

    def test_normalize_answer_cyrillic_preserved(self):
        assert _normalize_answer("Привет!") == "привет"

    def test_normalize_answer_diacritic_preserved(self):
        assert _normalize_answer("Café,") == "café"

    def test_grade_translation_cyrillic_correct_answer(self):
        # Correct answer contains Cyrillic; user submits same
        result = grade_translation("книга", "книга")
        assert result["is_correct"] is True

    def test_quiz_fill_in_blank_cyrillic(self):
        questions = [{"type": "fill_in_blank", "answer": "книга"}]
        result = process_quiz_submission(questions, {0: "книга"})
        assert result["correct_answers"] == 1

    def test_quiz_fill_in_blank_diacritic(self):
        questions = [{"type": "fill_in_blank", "answer": "café"}]
        result = process_quiz_submission(questions, {0: "café"})
        assert result["correct_answers"] == 1


class TestLevenshteinEmptyString:
    """_levenshtein handles empty inputs; _strict_text_match never passes empty to it."""

    def test_levenshtein_empty_a(self):
        assert _levenshtein("", "abc") == 3

    def test_levenshtein_empty_b(self):
        assert _levenshtein("abc", "") == 3

    def test_levenshtein_both_empty(self):
        assert _levenshtein("", "") == 0

    def test_strict_text_match_empty_user_does_not_call_levenshtein(self):
        # Empty user answer → False immediately, no levenshtein involved
        assert _strict_text_match("", ["apple"]) is False
        assert _strict_text_match("   ", ["apple"]) is False

    def test_strict_text_match_empty_candidate_skipped(self):
        # Empty/None candidates are skipped; valid candidate still graded
        assert _strict_text_match("apple", [None, "", "apple"]) is True
        assert _strict_text_match("apple", [None, ""]) is False

    def test_strict_text_match_very_short_word_no_levenshtein(self):
        # Words <4 chars — levenshtein tolerance does NOT apply
        # "is" vs "in": 1 edit, but both <4 chars → must be exact
        assert _strict_text_match("is", ["in"]) is False
        assert _strict_text_match("is", ["is"]) is True


class TestPartialMatching:
    """_grade_matching_pairs with fewer user pairs than correct pairs."""

    def test_partial_pairs_rejected(self):
        correct = [
            {"left": "cat", "right": "кот"},
            {"left": "dog", "right": "пёс"},
            {"left": "fish", "right": "рыба"},
        ]
        user = [{"left": "cat", "right": "кот"}]
        assert _grade_matching_pairs(user, correct) is False

    def test_extra_user_pairs_rejected(self):
        correct = [{"left": "cat", "right": "кот"}]
        user = [
            {"left": "cat", "right": "кот"},
            {"left": "dog", "right": "пёс"},
        ]
        assert _grade_matching_pairs(user, correct) is False

    def test_empty_user_pairs_rejected(self):
        correct = [{"left": "cat", "right": "кот"}]
        assert _grade_matching_pairs([], correct) is False

    def test_empty_correct_pairs_rejected(self):
        user = [{"left": "cat", "right": "кот"}]
        assert _grade_matching_pairs(user, []) is False

    def test_quiz_matching_partial_pairs(self):
        questions = [
            {
                "type": "matching",
                "pairs": [
                    {"left": "cat", "right": "кот"},
                    {"left": "dog", "right": "пёс"},
                ],
            }
        ]
        partial = [{"left": "cat", "right": "кот"}]
        result = process_quiz_submission(questions, {0: partial})
        assert result["correct_answers"] == 0


class TestEmptyAnswerScoreZero:
    """Score is 0 (not None/error) when user answer is empty."""

    def test_grade_translation_empty_is_incorrect(self):
        result = grade_translation("", "target")
        assert result["is_correct"] is False

    def test_grade_audio_fill_blank_empty_answer(self):
        items = [{"answer": "hello"}]
        result = grade_audio_fill_blank([""], items)
        assert result["score"] == 0
        assert result["passed"] is False
        assert result["correct_items"] == 0

    def test_grade_sentence_completion_empty_answer(self):
        items = [{"prompt": "I go ...", "answer": "home"}]
        result = grade_sentence_completion([""], items)
        assert result["score"] == 0
        assert result["correct_items"] == 0

    def test_grade_sentence_correction_multi_empty_answer(self):
        items = [{"incorrect_sentence": "I goed", "correct_sentence": "I went"}]
        result = grade_sentence_correction_multi([""], items)
        assert result["score"] == 0
        assert result["correct_items"] == 0

    def test_grade_collocation_matching_empty_user_pairs(self):
        correct = [{"phrase": "make a decision", "translation": "принять решение"}]
        result = grade_collocation_matching([], correct)
        assert result["score"] == 0
        assert result["correct_items"] == 0

    def test_quiz_fill_blank_empty_string_answer(self):
        questions = [{"type": "fill_in_blank", "answer": "apple"}]
        result = process_quiz_submission(questions, {0: ""})
        assert result["correct_answers"] == 0
        assert result["score"] == 0


class TestNoneInContentFields:
    """Graders must not raise exceptions when content fields are None."""

    def test_grade_audio_fill_blank_none_items(self):
        result = grade_audio_fill_blank(["any"], None)
        assert result["score"] == 0
        assert result["total_items"] == 0

    def test_grade_audio_fill_blank_item_with_none_answer(self):
        items = [{"answer": None}]
        result = grade_audio_fill_blank(["anything"], items)
        assert result["score"] == 0
        assert result["correct_items"] == 0

    def test_grade_sentence_completion_none_items(self):
        result = grade_sentence_completion(["home"], None)
        assert result["score"] == 0
        assert result["total_items"] == 0

    def test_grade_sentence_completion_item_with_none_answer(self):
        items = [{"prompt": "I go ...", "answer": None}]
        result = grade_sentence_completion(["home"], items)
        assert result["score"] == 0

    def test_grade_sentence_correction_multi_none_items(self):
        result = grade_sentence_correction_multi(["I went"], None)
        assert result["score"] == 0
        assert result["total_items"] == 0

    def test_grade_collocation_matching_none_correct_pairs(self):
        result = grade_collocation_matching([{"phrase": "x", "translation": "y"}], None)
        assert result["score"] == 0
        assert result["total_items"] == 0

    def test_grade_dictation_none_user_text(self):
        result = grade_dictation(None, "the cat sat")
        assert result["score"] == 0
        assert result["passed"] is False

    def test_grade_dictation_none_transcript(self):
        result = grade_dictation("the cat sat", None)
        assert result["score"] == 0
        assert result["total_words"] == 0

    def test_grade_translation_none_user_answer(self):
        result = grade_translation(None, "apple")
        assert result["is_correct"] is False

    def test_grade_translation_none_correct_answer(self):
        result = grade_translation("apple", None)
        assert result["is_correct"] is False
