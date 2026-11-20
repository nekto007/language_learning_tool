"""Authored optional packs are checked with the live web Grammar Lab grader."""
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from app.grammar_lab.content_validator import validate_exercise_content
from app.grammar_lab.services.grader import GrammarExerciseGrader

SOURCE = Path(__file__).parents[2] / 'MOBILE_GRAMMAR_SUPPLEMENTS_20261120.json'
PACK = json.loads(SOURCE.read_text())
ROWS = [(topic, exercise) for topic in PACK['topics'] for exercise in topic['exercises']]
TEXT_TYPES = {'fill_blank', 'error_correction', 'translation', 'transformation'}


def instance(row):
    return SimpleNamespace(id=row['order'], exercise_type=row['exercise_type'], content=row['content'])


def answer(row):
    content = row['content']
    if row['exercise_type'] == 'matching':
        return {str(i): str(i) for i in range(len(content['pairs']))}
    return content['correct_answer']


def test_optional_topics_have_stable_separate_identity_and_difficulty_progression():
    assert PACK['schema_version'] == 1
    assert {t['slug'] for t in PACK['topics']} == {'a1-subject-object-pronouns', 'a2-indefinite-pronouns'}
    for topic in PACK['topics']:
        assert topic['level'] in ('A1', 'A2')
        assert topic['content']['sections'] and topic['content']['tldr']
        assert 16 <= len(topic['exercises']) <= 24
        assert len({e['key'] for e in topic['exercises']}) == len(topic['exercises'])
        assert [e['order'] for e in topic['exercises']] == list(range(1, len(topic['exercises']) + 1))
        assert {e['difficulty'] for e in topic['exercises']} == {1, 2, 3}
        assert all('module_id' not in e and 'id' not in e for e in topic['exercises'])


@pytest.mark.parametrize('topic,row', ROWS, ids=[f'{t["level"]}:{e["key"]}' for t,e in ROWS])
def test_real_content_validator_and_grader_accept_every_expected_answer(topic, row):
    validate_exercise_content(row['exercise_type'], row['content'])
    grader = GrammarExerciseGrader()
    result = grader.grade(instance(row), answer(row))
    assert result['is_correct'] is True, (topic['slug'], row['key'], result)
    assert result.get('explanation')
    for alternative in row['content'].get('alternatives', []):
        assert grader.grade(instance(row), alternative)['is_correct'] is True, (row['key'], alternative)
    if row['exercise_type'] == 'multiple_choice':
        index = row['content']['options'].index(row['content']['correct_answer'])
        assert grader.grade(instance(row), str(index))['is_correct'] is True
        for wrong_index in range(len(row['content']['options'])):
            if wrong_index != index:
                assert grader.grade(instance(row), str(wrong_index))['is_correct'] is False


@pytest.mark.parametrize('topic,row', [(t,e) for t,e in ROWS if e['exercise_type']=='fill_blank'],
                         ids=[f'{t["level"]}:{e["key"]}' for t,e in ROWS if e['exercise_type']=='fill_blank'])
def test_hinted_blanks_also_accept_the_correct_complete_sentence(topic, row):
    content = row['content']
    assert content['question'].count('___') == 1
    assert '(' in content['question']  # Explicit pronoun/meaning disambiguates the requested form.
    sentence = re.sub(r'\s*\([^()]*\)', '', content['question']).replace('___', content['correct_answer'])
    assert GrammarExerciseGrader().grade(instance(row), sentence)['is_correct'] is True, (topic['slug'], row['key'])


@pytest.mark.parametrize('key,alternatives', [
    ('some-person', ['someone', 'somebody']),
    ('no-person', ['nobody', 'no one', 'no-one']),
    ('every-person', ['everyone', 'everybody']),
    ('negative-any-person', ['anyone', 'anybody']),
    ('correct-double-negative', ["I don't know anyone.", "I do not know anybody.", 'anybody', 'anyone']),
    ('correct-somebody-agreement', ['Somebody is waiting outside.', 'Someone is waiting outside.', 'is']),
])
def test_synonyms_and_contractions_are_not_marked_wrong(key, alternatives):
    topic = next(t for t in PACK['topics'] if t['slug']=='a2-indefinite-pronouns')
    row = next(e for e in topic['exercises'] if e['key']==key)
    for text in alternatives:
        assert GrammarExerciseGrader().grade(instance(row), text)['is_correct'] is True, text


def test_matching_requires_all_pairs_and_wrong_subject_object_forms_fail():
    grader = GrammarExerciseGrader()
    for _,row in ROWS:
        if row['exercise_type']=='matching':
            assert grader.grade(instance(row), {})['is_correct'] is False
            assert grader.grade(instance(row), {'0':'1', '1':'0', '2':'2', '3':'3'})['is_correct'] is False
    topic = PACK['topics'][0]
    by_key = {e['key']:e for e in topic['exercises']}
    for key,wrong in [('object-me','I'),('object-her','she'),('object-him','he'),('preposition-us','we'),('subject-we','us')]:
        assert grader.grade(instance(by_key[key]),wrong)['is_correct'] is False


def test_double_negative_task_preserves_the_authored_dont_constraint():
    row=next(e for e in PACK['topics'][1]['exercises'] if e['key']=='correct-double-negative')
    assert 'сохрани' in row['content']['question']
    assert GrammarExerciseGrader().grade(instance(row),'I know nobody.')['is_correct'] is False


def test_nothing_is_a_literal_pronoun_and_not_a_zero_article_alias():
    row=next(e for e in PACK['topics'][1]['exercises'] if e['key']=='no-thing')
    grader=GrammarExerciseGrader()
    assert grader.grade(instance(row),'nothing')['is_correct'] is True
    assert grader.grade(instance(row),'There is nothing in the box.')['is_correct'] is True
    for incorrect in ['—', '-', 'нет', 'zero', 'There is in the box.']:
        assert grader.grade(instance(row),incorrect)['is_correct'] is False, incorrect
