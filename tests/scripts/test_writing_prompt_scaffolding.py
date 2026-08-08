"""Regression tests for CNT-010 (cross-zone audit 2026-08-08).

Thirty-two `writing_prompt` lessons carried the A1 starter scaffolding
(`target_phrases: ["This is","That is","I have","I like"]` plus the matching
template and hint prefix) on top of prompts about something else. Because
`lessons.py:1775` makes `target_phrases` a completion gate in `guided` mode,
finishing the lesson depended on the learner happening to use a phrase from an
unrelated exercise.

The tests below pin the narrowness of the sweep: an authored `target_phrases`
list must survive, and a bespoke on-topic template must not be deleted along
with the generated ones.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.fix_writing_prompt_scaffolding import (
    fix_json_corpus,
    strip_starter_scaffolding,
)

GENERATED_TEMPLATE = 'This is a ___.\nThat is a ___.\nI have a ___.\nI like a ___.'
STARTER = ['This is', 'That is', 'I have', 'I like']


def _scaffolded(**overrides) -> dict:
    content = {
        'prompt': "Describe your plans for next week. Use 'going to'.",
        'mode': 'guided',
        'min_words': 30,
        'template': GENERATED_TEMPLATE,
        'hint_words': ['This is', 'That is', 'I have', 'I like', 'a', 'an',
                       'soon', 'tonight', 'next month'],
        'target_phrases': list(STARTER),
    }
    content.update(overrides)
    return content


class TestGateIsRemoved:
    def test_target_phrases_key_is_dropped(self):
        new, cleared = strip_starter_scaffolding(_scaffolded())
        assert 'target_phrases' in cleared
        assert 'target_phrases' not in new

    def test_the_prompt_and_checklist_are_untouched(self):
        original = _scaffolded(checklist=['Used going to twice'], min_sentences=5)
        new, _ = strip_starter_scaffolding(original)
        assert new['prompt'] == original['prompt']
        assert new['checklist'] == ['Used going to twice']
        assert new['min_sentences'] == 5
        assert new['mode'] == 'guided', 'mode must stay explicit, not fall back to auto-derive'

    def test_the_source_dict_is_not_mutated(self):
        original = _scaffolded()
        strip_starter_scaffolding(original)
        assert original['target_phrases'] == STARTER


class TestTemplateHandling:
    def test_generated_template_is_dropped(self):
        new, cleared = strip_starter_scaffolding(_scaffolded())
        assert 'template' in cleared and 'template' not in new

    def test_variant_wording_of_the_generated_template_is_also_dropped(self):
        variant = 'This is a ___.\nThat is a ___.\nI have a ___.\nI like ___.'
        new, cleared = strip_starter_scaffolding(_scaffolded(template=variant))
        assert 'template' in cleared and 'template' not in new

    def test_bespoke_template_survives(self):
        bespoke = "I like ___.\nI don't like ___.\nFor breakfast I eat ___."
        new, cleared = strip_starter_scaffolding(_scaffolded(template=bespoke))
        assert 'template' not in cleared
        assert new['template'] == bespoke


class TestHintWords:
    def test_only_the_generic_prefix_is_removed(self):
        new, cleared = strip_starter_scaffolding(_scaffolded())
        assert 'hint_words' in cleared
        assert new['hint_words'] == ['soon', 'tonight', 'next month']

    def test_hints_without_the_prefix_are_untouched(self):
        topical = ['soon', 'tonight', 'next month']
        new, cleared = strip_starter_scaffolding(_scaffolded(hint_words=topical))
        assert 'hint_words' not in cleared
        assert new['hint_words'] == topical

    def test_prefix_only_hints_drop_the_key(self):
        new, _ = strip_starter_scaffolding(
            _scaffolded(hint_words=['This is', 'That is', 'I have', 'I like', 'a', 'an'])
        )
        assert 'hint_words' not in new


class TestAuthoredContentIsSafe:
    @pytest.mark.parametrize('phrases', [
        ['Last year', 'When I was', 'I felt'],
        ['I can', "I can't"],
        ['This is', 'That is', 'I have'],           # subset, not the starter set
        ['This is', 'That is', 'I have', 'I like', 'I want'],  # superset
    ])
    def test_other_phrase_sets_are_left_alone(self, phrases):
        content = _scaffolded(target_phrases=phrases)
        new, cleared = strip_starter_scaffolding(content)
        assert cleared == []
        assert new is content

    def test_lesson_without_target_phrases_is_left_alone(self):
        content = {'prompt': 'Write freely.', 'mode': 'structured'}
        assert strip_starter_scaffolding(content) == (content, [])


class TestCorpusIsClean:
    def test_live_corpus_has_no_starter_scaffolding_left(self):
        source_dir = Path(__file__).resolve().parents[2] / 'module_completed' / 'fixed'
        if not source_dir.is_dir():
            pytest.skip('corpus is gitignored and absent in this checkout')
        assert fix_json_corpus(source_dir, apply=False) == 0

    def test_dry_run_never_writes_and_apply_is_idempotent(self, tmp_path):
        payload = {'module': {'lessons': [
            {'type': 'writing_prompt', 'content': _scaffolded()},
        ]}}
        path = tmp_path / 'module_A2_16_x.json'
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        before = path.read_text(encoding='utf-8')

        assert fix_json_corpus(tmp_path, apply=False) == 1
        assert path.read_text(encoding='utf-8') == before

        assert fix_json_corpus(tmp_path, apply=True) == 1
        assert 'target_phrases' not in path.read_text(encoding='utf-8')
        assert fix_json_corpus(tmp_path, apply=False) == 0
