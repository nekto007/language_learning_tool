"""Grade canonical mobile tokens without changing source keys or other graders."""

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.api.native_content import _converted, project
from app.curriculum.grading import process_quiz_submission


def checked(question, answer):
    result = process_quiz_submission([question], {"0": answer})
    return result["feedback"]["0"]["status"] == "correct"


@pytest.mark.parametrize(
    "kind", ["multiple_choice", "reading_comprehension", "listening_choice", "dialogue_completion"]
)
def test_numeric_authored_option_is_literal_while_ui_submits_its_index(kind):
    row = {
        "type": kind,
        "question": "When?",
        "options": ["2018", "five years", "recently", "childhood"],
        "correct": "2018",
    }
    original = deepcopy(row)
    assert checked(row, "0")
    assert checked(row, "2018")
    assert not checked(row, "1")
    assert not checked(row, "2019")
    value = SimpleNamespace(id=37, type="final_test", title="Year question", content={"questions": [row]}, module=None)
    [question] = project(value)
    converted = _converted(
        row, question, next(option["value"] for option in question["options"] if option["label"] == "2018")
    )
    assert checked(row, converted)
    assert row == original


def test_numeric_label_and_legacy_numeric_index_keys_are_unambiguous():
    base = {"type": "multiple_choice", "question": "Choose", "options": ["1", "0", "3"]}
    assert checked({**base, "correct": "1"}, "0")  # Authored literal label 1 is option0.
    assert not checked({**base, "correct": "1"}, "1")  # UI index1 selects label0.
    assert checked({**base, "correct": 1}, "1")  # Integer keys retain index semantics.
    assert checked({**base, "correct_index": "1"}, "1")  # Explicit index key retains semantics too.
    assert not checked({**base, "correct_index": "1"}, "0")
    legacy = {**base, "options": ["red", "blue", "green"], "correct": "1"}
    assert checked(legacy, "1") and checked(legacy, "blue")
    assert not checked(legacy, "0")


@pytest.mark.parametrize(
    ("expected", "response"), [(None, None), ("missing", "missing"), ("99", "99"), ("red", "missing")]
)
def test_failed_option_lookups_never_credit_two_matching_negative_indices(expected, response):
    row = {"type": "multiple_choice", "question": "Choose", "options": ["red", "blue"], "correct": expected}
    assert not checked(row, response)


@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        (["We", "have", "finished"], "We have finished."),
        (["We", "have", "finished", "."], "We have finished"),
        (["Have", "we", "finished", "?"], "Have we finished?"),
        (["He", "isn't", "here", "!"], "He isn't here."),
    ],
)
def test_ordering_accepts_canonical_mandatory_tokens_with_terminal_punctuation_variations(tokens, expected):
    row = {"type": "ordering", "question": "Arrange all tokens", "words": tokens, "correct": expected}
    value = SimpleNamespace(id=38, type="ordering_quiz", title="Order", content={"questions": [row]}, module=None)
    [question] = project(value)
    converted = _converted(row, question, json.dumps([str(index) for index in range(len(tokens))]))
    assert checked(row, converted)
    assert checked(row, expected)


@pytest.mark.parametrize(
    "wrong",
    [
        "We finished have.",
        "We have started.",
        "We have not finished.",
    ],
)
def test_ordering_does_not_ignore_wrong_words_or_order(wrong):
    row = {"type": "ordering", "question": "Arrange", "correct": "We have finished."}
    assert not checked(row, wrong)


def test_ordering_ignores_apostrophes_and_punctuation_but_keeps_word_order():
    row = {"type": "ordering", "question": "Arrange", "correct": "If he's late, we'll wait."}
    assert checked(row, "If he's late , we'll wait !")
    assert checked(row, "If hes late, well wait.")
    assert checked(row, "If he's late we'll wait.")
    assert not checked(row, "We'll wait, if he's late.")
    row = {"type": "ordering", "question": "Arrange", "correct": "We have finished."}
    for answer in ("We have finished,", "We, have finished.", "We. have finished."):
        assert checked(row, answer)


@pytest.mark.parametrize(
    "kind", ["multiple_choice", "dialogue_completion", "listening_choice", "reading_comprehension"]
)
def test_numeric_label_feedback_uses_same_resolved_option_as_grading(kind):
    row = {"type": kind, "question": "Choose", "options": ["1", "0", "3"], "correct": "1"}
    feedback = process_quiz_submission([row], {"0": "0"})["feedback"]["0"]
    assert feedback["status"] == "correct"
    assert feedback["correct_answer"] == feedback["user_answer"] == "1"


@pytest.mark.parametrize("answer", ["²", "9" * 10000], ids=["nondecimal-digit", "oversized-number"])
def test_unparseable_digit_input_stays_incorrect_without_an_exception(answer):
    row = {"type": "multiple_choice", "question": "Choose", "options": ["red", "blue"], "correct": "red"}
    assert not checked(row, answer)


def test_empty_or_punctuation_only_ordering_is_never_a_correct_answer():
    for expected in ["", ".!?", "   "]:
        row = {"type": "ordering", "question": "Arrange", "correct": expected}
        assert not checked(row, "")
        assert not checked(row, "...")


def test_offered_unicode_digit_label_is_valid_but_boolean_indices_are_not():
    row = {"type": "multiple_choice", "question": "Choose", "options": ["²", "blue"], "correct": "²"}
    assert checked(row, "0") and checked(row, "²")
    row = {"type": "multiple_choice", "question": "Choose", "options": ["red", "blue"], "correct": 1}
    assert not checked(row, True)
    assert not checked({**row, "correct": True}, "1")


def test_incorrect_numeric_reading_feedback_also_uses_option_labels():
    row = {"type": "reading_comprehension", "question": "Choose", "options": ["1", "0", "3"], "correct": "1"}
    feedback = process_quiz_submission([row], {"0": "1"})["feedback"]["0"]
    assert feedback["status"] == "incorrect"
    assert feedback["correct_answer"] == "1" and feedback["user_answer"] == "0"
