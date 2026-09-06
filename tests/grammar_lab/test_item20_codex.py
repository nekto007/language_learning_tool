"""Adversarial item-20 regressions; no production/content changes."""
import copy
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.curriculum.grading import _strict_text_match
from app.grammar_lab.models import GrammarExercise, GrammarTopic
from app.grammar_lab.services.grader import GrammarExerciseGrader
from scripts import fix_grammar_topics_3 as migration


@pytest.mark.parametrize('expected,answer', [
    ('The mummy is in the museum.', 'The mother is in the museum.'),
    ('They kid me.', 'They child me.'),
])
def test_lexical_variants_do_not_change_sense_or_part_of_speech(expected, answer):
    assert not _strict_text_match(answer, [expected])


def test_lab_preserves_possessive_number():
    exercise = SimpleNamespace(id=1, exercise_type='translation', content={
        'correct_answer': "The girl's books are here.", 'alternatives': [],
    })
    assert not GrammarExerciseGrader().grade(
        exercise, "The girls' books are here.")['is_correct']


def test_requested_mother_mom_and_contraction_still_match():
    exercise = SimpleNamespace(id=1, exercise_type='translation', content={
        'correct_answer': 'My mother does not work here.', 'alternatives': [],
    })
    assert GrammarExerciseGrader().grade(
        exercise, "My mom doesn't work here.")['is_correct']


def test_wrong_present_simple_agreement_stays_wrong():
    exercise = SimpleNamespace(id=1, exercise_type='fill_blank', content={
        'question': 'She ___ (read) every day.', 'correct_answer': 'reads',
        'alternatives': [],
    })
    assert not GrammarExerciseGrader().grade(exercise, 'She read every day.')['is_correct']


def test_reorder_accepts_fronted_now_with_same_tokens():
    path = Path(__file__).resolve().parents[2] / 'grammar_exercises_extra/grammar_extra_A2_15.json'
    data = json.loads(path.read_text())
    item = data['sessions'][0]['exercises'][9]
    assert item['content']['correct_answer'] == 'Mark is sweeping the yard now.'
    exercise = SimpleNamespace(id=1, exercise_type=item['exercise_type'], content=item['content'])
    assert GrammarExerciseGrader().grade(exercise, 'Now Mark is sweeping the yard.')['is_correct']


@pytest.fixture
def sql_case(db_session, monkeypatch):
    slug = 'codex-item20-' + uuid.uuid4().hex[:8]
    topic = GrammarTopic(slug=slug, title='Review', title_ru='Ревью', level='A1',
                         order=1, content={}, estimated_time=5, difficulty=1)
    db_session.add(topic)
    db_session.flush()
    meta = dict(migration.TOPICS['A1_10'], slug=slug)
    monkeypatch.setitem(migration.TOPICS, 'A1_10', meta)
    old = {'exercise_type': 'fill_blank', 'content': {
        'question': 'She ___ (read).', 'correct_answer': 'reads', 'alternatives': [],
    }, 'difficulty': 1, 'order': 1}
    new = copy.deepcopy(old)
    new['content'].update(question='He ___ (walk).', correct_answer='walks')
    change = {'slot': (1, 1), 'kind': 'replace', 'old': old, 'new': new}
    row = GrammarExercise(topic_id=topic.id, exercise_type=old['exercise_type'],
                          content=dict(old['content'], source='json_import'), difficulty=1, order=1)
    db_session.add(row)
    db_session.flush()
    sql = migration.emit_sql({'A1_10': [change]}, {})['2_apply']
    sql = sql.split('-- After apply every topic')[0]
    return topic, old, row, sql


def test_replace_sql_replay_does_not_duplicate(db_session, sql_case):
    topic, _, _, sql = sql_case
    db_session.execute(text(sql))
    db_session.execute(text(sql))
    assert db_session.query(GrammarExercise).filter_by(topic_id=topic.id).count() == 1


def test_replace_sql_stale_content_does_not_insert(db_session, sql_case):
    topic, _, row, sql = sql_case
    row.content = dict(row.content, explanation='An author changed this after the preflight.')
    db_session.flush()
    db_session.execute(text(sql))
    assert db_session.query(GrammarExercise).filter_by(topic_id=topic.id).count() == 1


def test_sql_does_not_match_module_import(db_session, sql_case):
    topic, old, row, _ = sql_case
    row.content = dict(row.content, source='module_import')
    db_session.flush()
    where = migration._where_exercise(topic.slug, old)
    assert db_session.execute(text(
        'SELECT count(*) FROM grammar_exercises WHERE ' + where)).scalar() == 0
