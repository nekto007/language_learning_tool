"""A no-article alias must never replace a literal vocabulary target."""

from types import SimpleNamespace

import pytest

from app.grammar_lab.services.grader import GrammarExerciseGrader


def exercise(expected, question="There is ___ in the box. (ничего)"):
    return SimpleNamespace(id=1, exercise_type="fill_blank", content={"question": question, "correct_answer": expected})


@pytest.mark.parametrize("expected", ["nothing", "none", "zero", "no", "0"])
def test_literal_word_or_number_is_not_an_article_placeholder(expected):
    grader = GrammarExerciseGrader()
    item = exercise(expected)
    assert grader.grade(item, expected)["is_correct"]
    for answer in ["—", "-", "нет артикля", "без артикля"]:
        assert not grader.grade(item, answer)["is_correct"], (expected, answer)


def test_nothing_accepts_word_and_complete_sentence_but_never_omission():
    grader = GrammarExerciseGrader()
    item = exercise("nothing")
    assert grader.grade(item, "nothing")["is_correct"]
    assert grader.grade(item, "There is nothing in the box.")["is_correct"]
    for answer in ["—", "-", "none", "нет", "zero", "There is in the box."]:
        assert not grader.grade(item, answer)["is_correct"], answer


def test_none_is_preserved_in_complete_sentence():
    grader = GrammarExerciseGrader()
    item = exercise("none", "___ of these answers is correct. (ни один)")
    assert grader.grade(item, "None of these answers is correct.")["is_correct"]
    assert not grader.grade(item, "Of these answers is correct.")["is_correct"]


@pytest.mark.parametrize(
    "expected", ["—", "–", "-", "−", "x", "ø", "∅", "zero article", "no article", "нет артикля", "без артикля"]  # noqa: RUF001 - exercise marker glyphs
)
def test_explicit_article_markers_still_accept_learner_aliases(expected):
    grader = GrammarExerciseGrader()
    item = exercise(expected, "She lives in ___ France. (артикль)")
    for answer in ["—", "-", "none", "nothing", "нет", "zero", "0", "ø", "без артикля"]:
        assert grader.grade(item, answer)["is_correct"], (expected, answer)
    assert grader.grade(item, "She lives in France.")["is_correct"]
    assert not grader.grade(item, "She lives in the France.")["is_correct"]
