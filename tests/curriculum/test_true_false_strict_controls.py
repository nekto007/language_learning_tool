"""Unknown input must never earn credit for an authored False in any grader."""

from types import SimpleNamespace

import pytest

from app.curriculum.grading import (
    process_final_test_submission,
    process_grammar_submission,
    process_quiz_submission,
)
from app.grammar_lab.services.grader import GrammarExerciseGrader


@pytest.fixture(params=["quiz", "grammar", "final_test", "grammar_lab"])
def check(request):
    def invoke(expected, answer):
        row = {"type": "true_false", "question": "The statement is true.", "correct_answer": expected}
        if request.param == "quiz":
            result = process_quiz_submission([row], {"0": answer})
            return result["feedback"]["0"]["status"] == "correct"
        if request.param == "grammar":
            result = process_grammar_submission([row], {"0": answer})
            return result["feedback"]["0"]["status"] == "correct"
        if request.param == "final_test":
            result = process_final_test_submission([row], {"0": answer})
            return result["feedback"]["0"]["is_correct"]
        exercise = SimpleNamespace(id=1, exercise_type="true_false", content=row)
        return GrammarExerciseGrader().grade(exercise, answer)["is_correct"]

    return invoke


@pytest.mark.parametrize("answer", ["banana", "", "false-ish", [], {}, None, 2, -1, 0.5])
def test_invalid_input_never_matches_authored_false(check, answer):
    assert check(False, answer) is False
    assert check("false", answer) is False


@pytest.mark.parametrize("expected", ["banana", "", "false-ish", [], {}, None, 2, -1, 0.5])
def test_invalid_authored_key_never_becomes_an_implicit_false(check, expected):
    assert check(expected, "false") is False
    assert check(expected, False) is False


@pytest.mark.parametrize("value", [True, 1, 1.0, "true", " TRUE ", "1", "yes", "Yes"])
def test_explicit_true_values_are_accepted_and_do_not_match_false(check, value):
    assert check(True, value) is True
    assert check(value, "true") is True
    assert check(False, value) is False


@pytest.mark.parametrize("value", [False, 0, 0.0, "false", " FALSE ", "0", "no", "No"])
def test_explicit_false_values_are_accepted_and_do_not_match_true(check, value):
    assert check(False, value) is True
    assert check(value, "false") is True
    assert check(True, value) is False


def test_string_false_feedback_is_false_instead_of_truthy_string_true():
    row = {"type": "true_false", "question": "Statement", "correct_answer": "false"}
    result = process_quiz_submission([row], {"0": "true"})
    assert result["feedback"]["0"]["status"] == "incorrect"
    assert result["feedback"]["0"]["correct_answer"] == "Ложь"
    invalid = process_quiz_submission([row], {"0": "banana"})
    assert invalid["feedback"]["0"]["status"] == "incorrect"
    assert invalid["feedback"]["0"]["user_answer"] == "banana"
