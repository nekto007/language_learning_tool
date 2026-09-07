"""Lesson audit item 26 — theory tables of the grammar lab.

Guards:
* every cell key used by the module corpus is known to ``_THEORY_CELL_ORDER``
  (an unknown key renders after the translation, at the end of the row);
* the B1 row shapes keep their authored reading order;
* a section that carries only a bare ``examples`` list renders in no template,
  so the corpus must not contain one.
"""
import glob
import json

import pytest

from app.grammar_lab.routes import _THEORY_CELL_ORDER, _order_theory_cells

CORPUS = sorted(glob.glob('module_completed/fixed/module_*.json'))


def _grammar_sections(path):
    with open(path, encoding='utf-8') as fh:
        module = json.load(fh).get('module') or {}
    lessons = [les for les in module.get("lessons", []) if les.get("type") == "grammar"]
    return lessons[0]['content'].get('sections', []) if lessons else []


def test_order_tuple_has_no_duplicates():
    assert len(_THEORY_CELL_ORDER) == len(set(_THEORY_CELL_ORDER))


@pytest.mark.skipif(not CORPUS, reason='content corpus is gitignored')
def test_every_corpus_cell_key_is_ordered():
    known = set(_THEORY_CELL_ORDER) | {'translation', 'audio'}
    unknown = set()
    for path in CORPUS:
        for section in _grammar_sections(path):
            for row in (section.get('table') or []):
                if isinstance(row, dict):
                    unknown |= {k for k in row if k not in known}
    assert not unknown, f'add these keys to _THEORY_CELL_ORDER: {sorted(unknown)}'


@pytest.mark.skipif(not CORPUS, reason='content corpus is gitignored')
def test_no_section_is_rendered_by_no_template():
    """``table`` / ``rules`` / ``usage`` are the only shapes the two grammar
    templates render; a section with only ``examples`` is invisible."""
    invisible = []
    for path in CORPUS:
        for i, section in enumerate(_grammar_sections(path)):
            if isinstance(section, dict) and not any(k in section for k in ('table', 'rules', 'usage')):
                invisible.append(f'{path.split("/")[-1]}#{i}')
    assert not invisible, f'sections no template renders: {invisible}'


@pytest.mark.parametrize('row, expected', [
    ({'phrasal': 'look up', 'literal': 'x', 'real_meaning': 'y', 'example': 'I looked it up.'},
     ['phrasal', 'literal', 'real_meaning', 'example']),
    ({'example': 'She looks after him.', 'phrasal': 'look after', 'wrong': '❌ looks him after'},
     ['phrasal', 'example', 'wrong']),
    ({'translation': 'x', 'with_pronoun': 'a', 'without_pronoun': 'b', 'note': 'n'},
     ['with_pronoun', 'without_pronoun', 'translation', 'note']),
    ({'translation_active': 'x', 'active': 'I post.', 'passive': 'It is posted.', 'translation_passive': 'y'},
     ['active', 'passive', 'translation_active', 'translation_passive']),
    ({'ing_form': 'boring', 'ed_form': 'bored', 'ed_translation': 'a', 'ing_translation': 'b'},
     ['ed_form', 'ed_translation', 'ing_form', 'ing_translation']),
    ({'translation': 'x', 'earlier': 'had eaten', 'later': 'before I left'},
     ['earlier', 'later', 'translation']),
    ({'v3': 'gone', 'v1': 'go'}, ['v1', 'v3']),
    ({'tag': "doesn't she?", 'statement': 'She works here,', 'example': 'x', 'translation': 'y'},
     ['statement', 'tag', 'example', 'translation']),
    ({'explanation': 'e', 'correct': 'c', 'wrong': 'w'}, ['wrong', 'correct', 'explanation']),
    ({'use_where': 'speech', 'idiom': 'break a leg', 'register': 'informal'},
     ['idiom', 'register', 'use_where']),
    ({'less_fewer': 'less money', 'noun': 'money', 'few_little': 'little money', 'translation': 'x'},
     ['noun', 'few_little', 'less_fewer', 'translation']),
])
def test_b1_row_shapes_keep_reading_order(row, expected):
    content = _order_theory_cells({'sections': [{'table': [dict(row)]}]})
    assert list(content['sections'][0]['table'][0]) == expected
