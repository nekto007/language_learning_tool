"""Lesson audit item 21 — corpus-wide grammar guards.

* reorder ``alternatives`` are other orders of exactly the same tokens;
* a bracketed verb hint in a fill-blank never spells the answer itself and
  the question keeps a single blank;
* the lab topic page renders every authored theory cell, not only the
  pronoun/form/example/translation quartet.
"""
import json
import re
import uuid
from collections import Counter
from pathlib import Path

import pytest

from app.grammar_lab.models import GrammarTopic

ROOT = Path(__file__).resolve().parents[2]
EXTRA = ROOT / 'grammar_exercises_extra'
TOKEN_RE = re.compile(r"[A-Za-z0-9']+|[.!?,]")


def _exercises():
    for path in sorted(EXTRA.glob('grammar_extra_*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        for session in data['sessions']:
            for exercise in session['exercises']:
                yield path.name, session['session_number'], exercise


@pytest.mark.skipif(not EXTRA.exists(), reason='authored grammar files are local data')
def test_reorder_alternatives_are_permutations_of_the_same_tokens():
    seen = 0
    for name, session, exercise in _exercises():
        if exercise['exercise_type'] != 'reorder':
            continue
        content = exercise['content']
        expected = Counter(t.lower() for t in TOKEN_RE.findall(content['correct_answer']))
        for alt in content.get('alternatives') or []:
            seen += 1
            assert Counter(t.lower() for t in TOKEN_RE.findall(alt)) == expected, (name, session, alt)
            assert alt.strip().lower() != content['correct_answer'].strip().lower(), (name, session, alt)
    assert seen >= 50


@pytest.mark.skipif(not EXTRA.exists(), reason='authored grammar files are local data')
def test_fill_blank_hints_are_base_forms_not_answers():
    hinted = 0
    for name, session, exercise in _exercises():
        if exercise['exercise_type'] != 'fill_blank':
            continue
        question = exercise['content'].get('question', '')
        match = re.search(r'___ \(([^()]+)\)', question)
        if not match:
            continue
        hinted += 1
        hint = match.group(1).strip().lower()
        answer = str(exercise['content']['correct_answer']).strip().lower()
        assert question.count('___') == 1, (name, session, question)
        # The hint may equal the answer for I/you/we/they («They ___ (play)» → play):
        # what it must never be is an auxiliary that spells the tense out.
        assert answer, (name, session, question)
        # Lexical do / be / have are fine hints; an inflected auxiliary would spell the tense out.
        assert hint.split()[0] not in ('does', 'did', 'is', 'are', 'am', 'was', 'were', 'has', 'had', 'not'), (name, session, question)
    assert hinted >= 70


def test_topic_page_renders_non_standard_theory_cells(db_session, authenticated_client):
    topic = GrammarTopic(
        slug=f'item21-cells-{uuid.uuid4().hex[:8]}', title='Cells', title_ru='Ячейки', level='A1', order=1,
        content={'introduction': 'x', 'sections': [{
            'subtitle': 'Правила добавления -s/-es',
            'table': [
                {'rule': 'Глаголы на -ch', 'ending': '+ es', 'example': 'watch → watches',
                 'translation': 'смотрит', 'audio': '[sound:x.mp3]'},
                {'verb': 'Do ... work?', 'example': 'Do you work?', 'translation': 'Ты работаешь?'},
                'not a mapping row',
            ]}]},
        estimated_time=5, difficulty=1,
    )
    db_session.add(topic)
    db_session.commit()
    response = authenticated_client.get(f'/grammar-lab/topic/{topic.slug}')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    assert 'Глаголы на -ch' in html and '+ es' in html and 'Do ... work?' in html
    assert '[sound:x.mp3]' not in html and 'not a mapping row' not in html
