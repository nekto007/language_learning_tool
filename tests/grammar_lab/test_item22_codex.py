"""Adversarial checks of item 22's new content and theory cells."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.grammar_lab.routes import _order_theory_cells
from app.grammar_lab.services.grader import GrammarExerciseGrader

ROOT = Path(__file__).resolve().parents[2]


def _exercise(session, order):
    path = ROOT / 'grammar_exercises_extra/grammar_extra_A1_12.json'
    if not path.exists():
        pytest.skip('Authored corpus is local data')
    data = json.loads(path.read_text())
    item = next(e for s in data['sessions'] if s['session_number'] == session
                for e in s['exercises'] if e['order'] == order)
    return SimpleNamespace(id=1, exercise_type=item['exercise_type'], content=item['content'])


@pytest.mark.parametrize('answer', ["don't usually", "usually don't", 'do not usually', 'usually do not'])
def test_negative_frequency_variants(answer):
    assert GrammarExerciseGrader().grade(_exercise(5, 1), answer)['is_correct']


@pytest.mark.parametrize('answer', ['', 'does not usually', 'usually does not'])
def test_negative_frequency_rejects_wrong_agreement(answer):
    assert not GrammarExerciseGrader().grade(_exercise(5, 1), answer)['is_correct']


def test_new_error_correction_accepts_swapped_time_adverbials():
    assert GrammarExerciseGrader().grade(
        _exercise(8, 8), 'We have breakfast every day at seven.')['is_correct']


def test_fronted_monthly_phrase_is_accepted():
    assert GrammarExerciseGrader().grade(
        _exercise(6, 7), 'Once a month she visits her grandparents.')['is_correct']


def test_how_often_translation_does_not_require_dialogue_dash():
    assert GrammarExerciseGrader().grade(
        _exercise(6, 5), 'How often do you go to the gym? Twice a week.')['is_correct']


def test_scale_and_question_translation_pairs_stay_adjacent():
    # Deliberately scramble the incoming order, as JSONB does.
    content = {'sections': [{'table': [
        {'example_translation': 'пример RU', 'example': 'example EN',
         'translation': 'слово RU', 'word': 'often', 'percentage': '70%'},
        {'translation_a': 'ответ RU', 'answer': 'answer EN',
         'translation_q': 'вопрос RU', 'question': 'question EN'},
    ]}]}
    result = _order_theory_cells(copy.deepcopy(content))
    rows = result['sections'][0]['table']
    assert list(rows[0]) == ['percentage', 'word', 'translation', 'example', 'example_translation']
    assert list(rows[1]) == ['question', 'translation_q', 'answer', 'translation_a']


def test_irregular_superlative_keeps_base_before_derived_form():
    # Actual row shape in module_A2_11_superlatives.json.
    content = {'sections': [{'table': [
        {'base': 'good', 'superlative': 'the best', 'translation': 'лучший'},
    ]}]}
    row = _order_theory_cells(content)['sections'][0]['table'][0]
    assert list(row) == ['base', 'superlative', 'translation']
