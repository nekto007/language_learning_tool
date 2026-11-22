# ruff: noqa: RUF001
"""Quiz text policy is shared by preview, course grammar, final and Lab.

These are pure grading tests: no lesson progress or real database writes.
"""
from types import SimpleNamespace

import pytest

from app.curriculum.grading import (
    process_final_test_submission,
    process_grammar_submission,
    process_quiz_submission,
    quiz_text_matches,
)
from app.grammar_lab.guided_learning import check_answer
from app.grammar_lab.services.grader import GrammarExerciseGrader
from app.utils.normalization import normalize_quiz_answer


def grade_all(row, answer):
    """Assert preview/submit have exactly one answer policy."""
    question = {'id': '0', 'input': 'text', 'prompt': 'Answer the question.'}
    exercise = SimpleNamespace(id=0, exercise_type=row['type'], content=row)
    return [
        process_grammar_submission([row], {'0': answer})['correct_answers'] == 1,
        process_quiz_submission([row], {'0': answer})['correct_answers'] == 1,
        process_final_test_submission([row], {'0': answer})['correct_answers'] == 1,
        GrammarExerciseGrader().grade(exercise, answer)['is_correct'],
        check_answer(row, question, answer, grammar=True)['correct'],
        check_answer(row, question, answer, grammar=False)['correct'],
        check_answer(row, question, answer, exercise=exercise)['correct'],
    ]


@pytest.mark.parametrize('answer', [
    'I DONT LIKE APPLES', 'i don’t like apples…', '“I don\'t” like apples!',
    'I don_t like apples?', 'I do not like apples', 'I don\u02bct like apples',
])
def test_case_all_punctuation_and_contractions_match_everywhere(answer):
    row = {'type': 'translation', 'correct_answer': "I don't like apples."}
    assert grade_all(row, answer) == [True] * 7


@pytest.mark.parametrize('answer', [
    'I like apples', 'I dont apples', 'apples I dont like', 'I dont like apple',
    'You dont like apples', 'I dont really like apples',
])
def test_missing_words_negation_order_and_different_forms_still_fail(answer):
    row = {'type': 'translation', 'correct_answer': "I don't like apples."}
    assert grade_all(row, answer) == [False] * 7


@pytest.mark.parametrize('kind', ['fill_blank', 'translation', 'transformation', 'error_correction'])
@pytest.mark.parametrize('field', ['alternatives', 'alternative_answers', 'acceptable_answers'])
def test_authored_aliases_have_same_policy_everywhere(kind, field):
    row = {'type': kind, 'correct_answer': 'My mum is here.', field: ['My mother is at home.']}
    assert grade_all(row, 'MY MOTHER IS AT HOME!!!') == [True] * 7


def test_apostrophes_are_not_separate_learning_targets():
    assert quiz_text_matches("the girls' books", ["the girl's books"])
    assert quiz_text_matches('DONT GO', ["Don't go."])
    assert not quiz_text_matches('DO GO', ["Don't go."])


def test_normalizer_removes_every_unicode_punctuation_but_preserves_words_and_symbols():
    assert normalize_quiz_answer('  “DÓN’T”_ «Go»…\n NOW！ ') == 'dónt go now'
    assert normalize_quiz_answer('A+B = 2') == 'a+b = 2'
    assert normalize_quiz_answer('do not') != normalize_quiz_answer('dont')
    assert normalize_quiz_answer(None) == ''


@pytest.mark.parametrize('answer', ['—', '-', 'no article', '0', 'нет артикля'])
def test_zero_article_explicit_marker_is_still_supported(answer):
    row = {'type': 'fill_blank', 'question': 'I like ___ music.', 'correct_answer': '—'}
    assert grade_all(row, answer) == [True] * 7


def test_zero_aliases_do_not_replace_actual_lexical_targets():
    assert not quiz_text_matches('—', ['nothing'])
    assert not quiz_text_matches('0', ['zero'])
    assert not quiz_text_matches('', ['—'])
    assert not quiz_text_matches('!!!', ['!!!'])
    assert not quiz_text_matches('aple', ['apple'])


@pytest.mark.parametrize('row,answer,expected', [
    ({'type': 'multiple_choice', 'options': ['1', '2', '3'], 'correct_answer': '1'}, '0', True),
    ({'type': 'multiple_choice', 'options': ['1', '2', '3'], 'correct_answer': '1'}, '1', False),
    ({'type': 'multiple_choice', 'options': ['1', '2', '3'], 'correct_index': 1}, '1', True),
    ({'type': 'multiple_choice', 'options': ['2018', '2020'], 'correct_answer': '2018'}, '0', True),
    ({'type': 'multiple_choice', 'options': ['Do not', "Don't"], 'correct_answer': "Don't"}, '1', True),
    ({'type': 'multiple_choice', 'options': ['Apple!', 'Banana?'], 'correct_answer': 'APPLE'}, 'apple?', True),
    ({'type': 'multiple_choice', 'options': ['Apple!', 'Banana?'], 'correct_answer': 'Apple!'}, '-1', False),
    ({'type': 'multiple_choice', 'options': ['Apple!', 'Banana?'], 'correct_answer': 'Banana?'}, '2', False),
    ({'type': 'multiple_choice', 'options': ['Apple!', 'Banana?'], 'correct_answer': 'missing'}, 'missing', False),
])
def test_mc_numeric_labels_indexes_and_invalid_values(row, answer, expected):
    assert (process_quiz_submission([row], {'0': answer})['correct_answers'] == 1) is expected
    assert (process_grammar_submission([row], {'0': answer})['correct_answers'] == 1) is expected
    assert (process_final_test_submission([row], {'0': answer})['correct_answers'] == 1) is expected
    exercise = SimpleNamespace(id=0, exercise_type='multiple_choice', content=row)
    assert GrammarExerciseGrader().grade(exercise, answer)['is_correct'] is expected


@pytest.mark.parametrize('answer,expected', [('I am here!', True), ('here am I', False), ('I here', False)])
def test_reorder_preserves_word_order_and_completeness(answer, expected):
    row = {'type': 'reorder', 'correct_answer': 'I am here.'}
    assert (process_quiz_submission([row], {'0': answer})['correct_answers'] == 1) is expected
    assert (process_grammar_submission([row], {'0': answer})['correct_answers'] == 1) is expected
    assert (process_final_test_submission([row], {'0': answer})['correct_answers'] == 1) is expected


def test_final_test_exact_75_boundary():
    questions = [{'type': 'fill_blank', 'correct_answer': 'is'}] * 4
    assert process_final_test_submission(questions, {'0': 'is', '1': 'IS!', '2': 'is'})['passed']
    assert not process_final_test_submission(questions, {'0': 'is', '1': 'is'})['passed']


def test_fraction_below_50_never_passes_by_integer_rounding():
    questions = [{'type': 'fill_blank', 'correct_answer': 'is'}] * 201
    answers = {str(index): 'is' for index in range(100)}
    for grader in (process_quiz_submission, process_grammar_submission):
        result = grader(questions, answers)
        assert result['correct_answers'] == 100
        assert result['score'] == 49.75
        assert result['score'] < 50


def test_final_fraction_below_75_keeps_same_score_and_pass_decision():
    questions = [{'type': 'fill_blank', 'correct_answer': 'is'}] * 201
    answers = {str(index): 'is' for index in range(150)}
    result = process_final_test_submission(questions, answers)
    assert result['correct_answers'] == 150
    assert result['score'] == 74.63
    assert result['passed'] is False
