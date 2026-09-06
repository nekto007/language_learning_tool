"""Item 21: real JSONB rendering and overlooked corpus ambiguities."""
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.grammar_lab.models import GrammarTopic
from app.grammar_lab.services.grader import GrammarExerciseGrader

ROOT = Path(__file__).resolve().parents[2]


def _page(db_session, client, rows):
    topic = GrammarTopic(
        slug='codex21-' + uuid.uuid4().hex[:10], title='Cells', title_ru='Ячейки',
        level='A1', order=1, estimated_time=5, difficulty=1,
        content={'introduction': 'x', 'sections': [{'subtitle': 'Rules', 'table': rows}]},
    )
    db_session.add(topic)
    db_session.commit()
    slug = topic.slug
    # Force the JSONB round trip, not the insertion-ordered Python dictionary.
    db_session.expire_all()
    response = client.get('/grammar-lab/topic/' + slug)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_jsonb_keeps_semantic_column_order(db_session, authenticated_client):
    html = _page(db_session, authenticated_client, [{
        'pronoun': 'SUBJECT_MARKER', 'form': 'FORM_MARKER',
        'example': 'EXAMPLE_MARKER', 'translation': 'TRANSLATION_MARKER',
    }])
    positions = [html.index(s) for s in (
        'SUBJECT_MARKER', 'FORM_MARKER', 'EXAMPLE_MARKER', 'TRANSLATION_MARKER')]
    assert positions == sorted(positions)


def test_arbitrary_cells_are_escaped_and_audio_skipped(db_session, authenticated_client):
    html = _page(db_session, authenticated_client, [{
        'rule': '&lt;img src=x onerror=alert(2121)&gt;',
        'pattern': '<script>alert(2121)</script>', 'audio': 'HIDDEN_AUDIO_MARKER',
    }, 'NOT_A_ROW_MARKER'])
    assert '<img src=x onerror=alert(2121)>' not in html
    assert '<script>alert(2121)</script>' not in html
    assert '&lt;img src=x onerror=alert(2121)&gt;' in html
    assert '&lt;script&gt;alert(2121)&lt;/script&gt;' in html
    assert 'HIDDEN_AUDIO_MARKER' not in html
    assert 'NOT_A_ROW_MARKER' not in html


def _items(topic):
    path = ROOT / 'grammar_exercises_extra' / f'grammar_extra_{topic}.json'
    if not path.exists():
        pytest.skip('Authored corpus is local data')
    data = json.loads(path.read_text())
    return {(s['session_number'], e['order']): e
            for s in data['sessions'] for e in s['exercises']}


@pytest.mark.parametrize('topic,slot,verb', [
    ('A2_20', (3, 2), 'exercise'),
    ('A2_23', (1, 1), 'go'),
    ('B2_10', (1, 2), 'make'),
    ('B2_12', (2, 2), 'build'),
])
def test_lexical_blanks_have_base_verb_hint(topic, slot, verb):
    item = _items(topic)[slot]
    assert item['exercise_type'] == 'fill_blank'
    assert f'({verb})' in item['content']['question']


@pytest.mark.parametrize('topic,canonical,answer', [
    ('A1_10', 'He goes to work at nine every day.', 'He goes to work every day at nine.'),
    ('A2_16', 'You are presenting the project at noon tomorrow.',
     'You are presenting the project tomorrow at noon.'),
])
def test_two_time_adverbials_can_swap(topic, canonical, answer):
    item = next(e for e in _items(topic).values()
                if e['exercise_type'] == 'reorder' and e['content']['correct_answer'] == canonical)
    exercise = SimpleNamespace(id=1, exercise_type='reorder', content=item['content'])
    assert GrammarExerciseGrader().grade(exercise, answer)['is_correct']
