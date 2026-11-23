"""Dictation must ignore typography without crediting added words or rounding up a fail."""
import pytest

from app.curriculum.grading import grade_dictation, grade_dictation_gaps


@pytest.mark.parametrize('answer', ["I'M HERE!", 'I’m here.', 'Iʼm here…', 'Im HERE', '  im\nHERE  '])
def test_apostrophe_variants_and_case_do_not_change_word_accuracy(answer):
    result = grade_dictation(answer, "I'm here")
    assert result['correct_words'] == result['total_words'] == 2
    assert result['score'] == 100 and result['passed']


def test_removed_apostrophe_does_not_expand_a_contraction_into_two_words():
    result = grade_dictation('I am here', "I'm here")
    assert result['score'] < 100


def test_trailing_words_are_included_in_accuracy_and_feedback():
    result = grade_dictation('I am here today', 'I am here')
    assert result['correct_words'] == 3
    assert result['total_words'] == 4
    assert result['score'] == 75
    assert result['word_results'][-1] == {'word': '', 'user_word': 'today', 'correct': False}


def test_just_below_half_stays_below_the_passing_bar():
    result = grade_dictation(' '.join(['yes'] * 101 + ['no'] * 102), ' '.join(['yes'] * 203))
    assert result['score'] == 49.75
    assert not result['passed']


def test_display_precision_cannot_promote_a_failed_dictation_to_fifty():
    result = grade_dictation(' '.join(['a'] * 10000 + ['b'] * 10001), ' '.join(['a'] * 20001))
    assert result['score'] < 50
    assert not result['passed']


def test_deleted_word_retains_the_existing_positional_grading_policy():
    result = grade_dictation('one three four', 'one two three four')
    assert result['correct_words'] == 1 and result['total_words'] == 4


def test_extra_word_in_one_gap_never_displaces_the_next_gap():
    result = grade_dictation_gaps(['am extra', 'home'], [{'answer': 'am'}, {'answer': 'home'}])
    assert result['correct_words'] == 2 and result['total_words'] == 3
    assert result['score'] == 66.67
    assert result['word_results'][-1] == {'word': 'home', 'user_word': 'home', 'correct': True}
