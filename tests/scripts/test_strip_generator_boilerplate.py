"""Regression tests for CNT-006 / CNT-007 / CNT-026 (cross-zone audit 2026-08-08).

Three generator seams removed by `scripts/strip_generator_boilerplate.py`:
the "It appears during focused classroom practice." tail on vocabulary examples,
the "This reading version adds context one." tail on reading lines, and the
"Перевод фразы из словаря модуля." stub explanation.

What these tests pin down is the *narrowness* of the deletion — the rules must
not touch a real sentence that merely resembles the filler, and they must be
idempotent, because the corpus is gitignored and re-run by hand in every
checkout.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.strip_generator_boilerplate import (
    fix_json_corpus,
    fix_lesson,
    strip_reading_filler,
    strip_stub_explanations,
    strip_vocab_filler,
)


class TestVocabularyFiller:
    """CNT-006."""

    def test_trailing_filler_is_removed(self):
        content = {
            'vocabulary': [
                {'english': 'apartment',
                 'example': 'We rent a small apartment. It appears during focused classroom practice.'}
            ]
        }
        new, hits = strip_vocab_filler(content)
        assert hits == 1
        assert new['vocabulary'][0]['example'] == 'We rent a small apartment.'

    def test_other_fields_survive(self):
        content = {
            'vocabulary': [
                {'english': 'x', 'russian': 'икс', 'audio': '/static/a.mp3',
                 'example': 'A. It appears during focused classroom practice.'}
            ]
        }
        new, _ = strip_vocab_filler(content)
        item = new['vocabulary'][0]
        assert item['russian'] == 'икс' and item['audio'] == '/static/a.mp3'

    def test_clean_example_is_left_alone(self):
        content = {'vocabulary': [{'example': 'We rent a small apartment.'}]}
        new, hits = strip_vocab_filler(content)
        assert hits == 0 and new is content

    def test_filler_in_the_middle_is_not_touched(self):
        """Only the trailing form is generator output; mid-sentence text is authored."""
        sentence = 'It appears during focused classroom practice. Then we move on.'
        content = {'vocabulary': [{'example': sentence}]}
        _, hits = strip_vocab_filler(content)
        assert hits == 0

    def test_running_twice_changes_nothing(self):
        content = {'vocabulary': [{'example': 'A. It appears during focused classroom practice.'}]}
        once, _ = strip_vocab_filler(content)
        twice, hits = strip_vocab_filler(once)
        assert hits == 0 and twice == once


class TestReadingFiller:
    """CNT-007."""

    @pytest.mark.parametrize('variant', ['one', 'two', 'three', 'ten'])
    def test_every_numbered_variant_is_removed(self, variant):
        line = f'The crime rate has decreased. This reading version adds context {variant}.'
        content = {'text': {'lines': [{'text': line}]}}
        new, hits = strip_reading_filler(content)
        assert hits == 1
        assert new['text']['lines'][0]['text'] == 'The crime rate has decreased.'

    def test_sibling_line_fields_survive(self):
        content = {'text': {'title': 'Crime', 'lines': [
            {'text': 'A. This reading version adds context one.', 'translation': 'Текст.', 'audio': '/a.mp3'},
        ]}}
        new, _ = strip_reading_filler(content)
        assert new['text']['title'] == 'Crime'
        assert new['text']['lines'][0]['translation'] == 'Текст.'
        assert new['text']['lines'][0]['audio'] == '/a.mp3'

    def test_clean_line_is_left_alone(self):
        content = {'text': {'lines': [{'text': 'The law protects citizens.'}]}}
        _, hits = strip_reading_filler(content)
        assert hits == 0

    def test_missing_text_block_is_tolerated(self):
        assert strip_reading_filler({'exercises': []}) == ({'exercises': []}, 0)


class TestStubExplanations:
    """CNT-026 — the key is dropped, not blanked."""

    def test_stub_key_is_dropped_from_flat_exercises(self):
        content = {'exercises': [{'question': 'q', 'explanation': 'Перевод фразы из словаря модуля.'}]}
        new, hits = strip_stub_explanations(content)
        assert hits == 1
        assert 'explanation' not in new['exercises'][0]
        assert new['exercises'][0]['question'] == 'q'

    def test_stub_key_is_dropped_inside_test_sections(self):
        content = {'test_sections': [
            {'title': 'A', 'exercises': [{'explanation': 'Перевод фразы из словаря модуля.'}]},
        ]}
        new, hits = strip_stub_explanations(content)
        assert hits == 1
        assert 'explanation' not in new['test_sections'][0]['exercises'][0]
        assert new['test_sections'][0]['title'] == 'A'

    def test_real_explanation_survives(self):
        content = {'exercises': [{'explanation': 'Present Perfect используется для опыта.'}]}
        _, hits = strip_stub_explanations(content)
        assert hits == 0

    def test_explanation_that_merely_contains_the_stub_survives(self):
        content = {'exercises': [
            {'explanation': 'Перевод фразы из словаря модуля. Обратите внимание на артикль.'},
        ]}
        _, hits = strip_stub_explanations(content)
        assert hits == 0


class TestRuleTargeting:
    """A rule must only fire on the lesson types it was written for."""

    def test_vocabulary_rule_does_not_fire_on_a_reading_lesson(self):
        content = {'vocabulary': [{'example': 'A. It appears during focused classroom practice.'}]}
        _, hits = fix_lesson('reading', content)
        assert hits == {}

    def test_explanation_rule_does_not_fire_on_a_quiz_lesson(self):
        content = {'exercises': [{'explanation': 'Перевод фразы из словаря модуля.'}]}
        assert fix_lesson('quiz', content)[1] == {}
        assert fix_lesson('translation_quiz', content)[1] == {'CNT-026': 1}


class TestCorpusIsClean:
    def test_live_corpus_has_no_remaining_seams(self):
        source_dir = Path(__file__).resolve().parents[2] / 'module_completed' / 'fixed'
        if not source_dir.is_dir():
            pytest.skip('corpus is gitignored and absent in this checkout')
        assert fix_json_corpus(source_dir, apply=False) == {}

    def test_dry_run_never_writes(self, tmp_path):
        payload = {'module': {'lessons': [
            {'type': 'vocabulary', 'content': {'vocabulary': [
                {'example': 'A. It appears during focused classroom practice.'},
            ]}},
        ]}}
        path = tmp_path / 'module_A1_1_x.json'
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        before = path.read_text(encoding='utf-8')

        assert fix_json_corpus(tmp_path, apply=False) == {'CNT-006': 1}
        assert path.read_text(encoding='utf-8') == before

        assert fix_json_corpus(tmp_path, apply=True) == {'CNT-006': 1}
        assert 'focused classroom practice' not in path.read_text(encoding='utf-8')
        assert fix_json_corpus(tmp_path, apply=False) == {}
