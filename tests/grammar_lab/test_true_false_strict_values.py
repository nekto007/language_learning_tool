"""Unknown truthy/falsy objects must not earn grammar accuracy or progress."""

from types import SimpleNamespace

import pytest

from app.grammar_lab.services.grader import GrammarExerciseGrader


def exercise(correct):
    return SimpleNamespace(
        id=1, exercise_type="true_false", content={"question": "Is this correct?", "correct_answer": correct}
    )


@pytest.mark.parametrize("correct", [True, False])
@pytest.mark.parametrize(
    "answer",
    [None, "", " ", "banana", "unknown", "not true", [], {}, [False], {"value": False}, 2, -1, 0.5, float("nan")],
)
def test_unknown_values_never_match_either_true_or_false(correct, answer):
    assert GrammarExerciseGrader().grade(exercise(correct), answer)["is_correct"] is False


@pytest.mark.parametrize("answer", [True, 1, 1.0, "true", "TRUE", " true ", "1", "yes"])
def test_explicit_true_values_are_preserved(answer):
    grader = GrammarExerciseGrader()
    assert grader.grade(exercise(True), answer)["is_correct"] is True
    assert grader.grade(exercise(False), answer)["is_correct"] is False


@pytest.mark.parametrize("answer", [False, 0, 0.0, "false", "FALSE", " false ", "0", "no"])
def test_explicit_false_values_are_preserved(answer):
    grader = GrammarExerciseGrader()
    assert grader.grade(exercise(False), answer)["is_correct"] is True
    assert grader.grade(exercise(True), answer)["is_correct"] is False


@pytest.mark.parametrize("expected", [None, "", "unknown", [], {}, 2])
def test_invalid_authored_boolean_cannot_accept_an_answer(expected):
    for answer in [True, False, "true", "false"]:
        result = GrammarExerciseGrader().grade(exercise(expected), answer)
        assert result["is_correct"] is False and result["error"]
