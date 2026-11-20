"""Original Future Perfect practice remains solvable through web/native graders."""
from copy import deepcopy
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from app.api.native_content import _converted, _question
from app.cli.grammar_supplements import validate_pack
from app.grammar_lab.content_validator import validate_exercise_content
from app.grammar_lab.services.grader import GrammarExerciseGrader
from scripts.audit_native_grammar_practice import widget_answer

ROOT = Path(__file__).parents[2]
PACK = json.loads((ROOT / 'MOBILE_GRAMMAR_FUTURE_PERFECT_20261120.json').read_text())
TOPIC = PACK['topics'][0]
ROWS = TOPIC['exercises']


def exercise(row):
    return SimpleNamespace(id=row['order'], exercise_type=row['exercise_type'], content=row['content'])


def canonical(row):
    if row['exercise_type'] == 'matching':
        return {str(i): str(i) for i in range(len(row['content']['pairs']))}
    return row['content']['correct_answer']


def test_pack_is_additive_20_original_items_and_all_instructions_name_target():
    before = deepcopy(PACK)
    validate_pack(PACK)
    assert PACK == before
    assert len(PACK['topics']) == 1 and TOPIC['slug'] == 'b2-future-perfect'
    assert TOPIC['level'] == 'B2' and len(ROWS) == 20
    assert len({row['key'] for row in ROWS}) == 20
    assert [row['order'] for row in ROWS] == list(range(1, 21))
    assert {row['difficulty'] for row in ROWS} == {1, 2, 3}
    assert all('module_id' not in row and 'id' not in row for row in ROWS)
    assert all('instruction' in row['content'] for row in ROWS)
    assert all('Future Perfect' in row['content']['instruction'] or 'Future Perfect' in row['content'].get('question', '') for row in ROWS)
    original = json.loads((ROOT / 'MOBILE_GRAMMAR_SUPPLEMENTS_20261120.json').read_text())
    assert len(original['topics']) == 2 and sum(len(topic['exercises']) for topic in original['topics']) == 40
    assert TOPIC['slug'] not in {topic['slug'] for topic in original['topics']}


@pytest.mark.parametrize('row', ROWS, ids=[row['key'] for row in ROWS])
def test_every_canonical_and_authored_alternative_passes_real_grader(row):
    validate_exercise_content(row['exercise_type'], row['content'])
    grader = GrammarExerciseGrader()
    assert grader.grade(exercise(row), canonical(row))['is_correct'] is True
    for alternative in row['content'].get('alternatives', []):
        assert grader.grade(exercise(row), alternative)['is_correct'] is True, alternative
    if row['exercise_type'] == 'multiple_choice':
        answer = row['content']['options'].index(row['content']['correct_answer'])
        for index in range(len(row['content']['options'])):
            assert grader.grade(exercise(row), str(index))['is_correct'] is (index == answer)


@pytest.mark.parametrize('row', ROWS, ids=[row['key'] for row in ROWS])
def test_every_authored_answer_is_reachable_through_actual_native_widget(row):
    proxy = SimpleNamespace(id=row['order'], type='grammar', content={}, module=SimpleNamespace(level=SimpleNamespace(code='B2')))
    authored = {**row['content'], 'type': 'match' if row['exercise_type'] == 'matching' else row['exercise_type']}
    question = _question(proxy, authored, 0)
    expected_widget = {'multiple_choice': 'choice', 'matching': 'match', 'reorder': 'order'}.get(row['exercise_type'], 'text')
    assert question['input'] == expected_widget
    assert row['content']['instruction'] in question.get('instruction', '')
    assert 'correct_answer' not in question and 'answer' not in question
    response = widget_answer(exercise(row), question)
    converted = _converted(authored, question, response, grammar=True)
    assert GrammarExerciseGrader().grade(exercise(row), converted)['is_correct'] is True


@pytest.mark.parametrize('row', [row for row in ROWS if row['exercise_type'] == 'fill_blank'], ids=[row['key'] for row in ROWS if row['exercise_type'] == 'fill_blank'])
def test_blanks_accept_correct_complete_sentences_despite_verb_hints(row):
    content = row['content']
    assert content['question'].count('___') == 1
    sentence = re.sub(r'\s*\([^()]*\)', '', content['question']).replace('___', content['correct_answer'])
    assert GrammarExerciseGrader().grade(exercise(row), sentence)['is_correct'] is True, sentence


def test_required_form_rejects_otherwise_possible_future_simple_and_v2():
    by_key = {row['key']: row for row in ROWS}
    grader = GrammarExerciseGrader()
    for key, incorrect in [
        ('finish-by-six', 'will finish'),
        ('write-three-reports', 'will have wrote'),
        ('question-have', 'has'),
        ('build-bridge', 'will have build'),
        ('translate-fixed-words', 'We will finish the report by Friday.'),
    ]:
        assert grader.grade(exercise(by_key[key]), incorrect)['is_correct'] is False, (key, incorrect)


def test_theory_does_not_teach_by_as_an_automatic_tense_selector():
    content = TOPIC['content']
    prose = json.dumps(content, ensure_ascii=False)
    assert 'by/before' in prose
    assert 'не требует только этого времени' in prose
    assert 'I will finish the report by Friday.' in prose
    assert 'by the time you arrive' in prose.lower()
    assert 'другие употребления' in prose


def test_multiple_choice_correct_positions_are_balanced():
    assert [row['content']['options'].index(row['content']['correct_answer']) for row in ROWS if row['exercise_type'] == 'multiple_choice'] == [0, 1, 2, 3]


@pytest.mark.parametrize('row', [row for row in ROWS if row['exercise_type'] == 'reorder'], ids=[row['key'] for row in ROWS if row['exercise_type'] == 'reorder'])
def test_natural_same_token_time_orders_are_reachable_and_accepted(row):
    assert row['content']['alternatives']
    assert 'в конец' in row['content']['instruction']
    proxy = SimpleNamespace(id=row['order'], type='grammar', content={}, module=SimpleNamespace(level=SimpleNamespace(code='B2')))
    authored = {**row['content'], 'type': 'reorder'}
    question = _question(proxy, authored, 0)
    for alternative in row['content']['alternatives']:
        variant = exercise(row)
        variant.content = {**variant.content, 'correct_answer': alternative}
        response = widget_answer(variant, question)
        converted = _converted(authored, question, response, grammar=True)
        assert GrammarExerciseGrader().grade(exercise(row), converted)['is_correct'] is True, alternative
