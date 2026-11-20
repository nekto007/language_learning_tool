"""Advanced recaps replace actual heading-only summaries with usable rules."""
from copy import deepcopy
import json
from pathlib import Path
import re

import pytest

from app.grammar_lab.recap_manifest import PatchConflict, validate_manifest

ROOT = Path(__file__).parents[2]
SOURCE = ROOT / 'MOBILE_GRAMMAR_ADVANCED_RECAPS_20261120.json'


def test_reviewed_advanced_recaps_have_compact_rules_and_exact_before_after():
    document = json.loads(SOURCE.read_text())
    assert document['patch_kind'] == 'advanced_recaps'
    entries = validate_manifest(document)
    assert len(entries) == 15
    assert sum(entry.get('theory_only', False) for entry in entries) == 4
    identities = {(entry['level'], entry['module_order']) for entry in entries}
    assert {('B1', i) for i in range(8, 13)} | {('B2', 6), ('C1', 3), ('C1', 10)} <= identities
    for entry in entries:
        if entry.get('theory_only'):
            assert len(entry['changes']) == 1
            assert entry['changes'][0]['path'][0] in ('important_notes', 'sections')
            continue
        recap = next(change for change in entry['changes'] if change['path'] == ['tldr'])
        assert any(re.fullmatch(r'\s*<strong>[^<]+</strong>\s*', line) for line in recap['before'])
        assert 3 <= len(recap['after']) <= 5
        assert all(len(line) <= 260 for line in recap['after'])
        assert not any(re.fullmatch(r'\s*<strong>[^<]+</strong>\s*', line) for line in recap['after'])
        assert any('<em>' in line for line in recap['after'])


@pytest.mark.parametrize('field', ['audio', 'correct_answer', 'id', 'options', 'external_key'])
def test_advanced_table_allowlist_never_allows_answers_audio_or_identity(field):
    document = json.loads(SOURCE.read_text())
    entry = document['entries'][0]
    entry['changes'].append({'path': ['sections', 0, 'table', 0, field], 'before': 'old', 'after': 'new'})
    with pytest.raises(PatchConflict):
        validate_manifest(document)


def test_table_corrections_are_only_reviewed_nonempty_strings():
    document = json.loads(SOURCE.read_text())
    entry = next(entry for entry in document['entries'] if entry['file'] == 'module_B1_12_internet_and_social_media.json')
    change = next(change for change in entry['changes'] if change['path'] == ['sections', 0, 'table', 0, 'subject'])
    assert change['before'] == 'I/He/She/It'
    assert change['after'] == 'He/She/It'
    broken = deepcopy(document)
    target = next(e for e in broken['entries'] if e['file'] == entry['file'])
    next(c for c in target['changes'] if c['path'] == change['path'])['after'] = {'unreviewed': True}
    with pytest.raises(PatchConflict, match='strings'):
        validate_manifest(broken)


@pytest.mark.parametrize('kind', ['mobile_recaps', 'reviewed_advanced', 'empty_examples'])
def test_theory_only_flag_cannot_bypass_other_patch_kind_restrictions(kind):
    document = json.loads(SOURCE.read_text())
    entry = next(entry for entry in document['entries'] if entry.get('theory_only'))
    document['entries'] = [entry]
    document['patch_kind'] = kind
    with pytest.raises(PatchConflict, match='Theory-only'):
        validate_manifest(document)


@pytest.mark.parametrize('path', [['rule'], ['description'], ['tldr'], ['sections', 0, 'table', 0, 'audio'], ['sections', 0, 'table', 0, 'correct_answer']])
def test_notes_only_entries_do_not_enable_generic_content_patches(path):
    document = json.loads(SOURCE.read_text())
    entry = next(entry for entry in document['entries'] if entry.get('theory_only'))
    document['entries'] = [entry]
    entry['changes'] = [{'path': path, 'before': 'Old', 'after': 'New'}]
    with pytest.raises(PatchConflict):
        validate_manifest(document)


@pytest.mark.parametrize('path', [
    ['important_notes', 0], ['sections', 0, 'notes', 0],
    ['sections', 0, 'table', 0, 'note'], ['sections', 0, 'table', 0, 'form'],
    ['summary', 'table', 0, 'example'], ['summary', 'table', 0, 'translation'],
])
def test_scalar_display_notes_allowlist_is_explicit_and_strings_only(path):
    document = json.loads(SOURCE.read_text())
    entry = next(entry for entry in document['entries'] if entry.get('theory_only'))
    document['entries'] = [entry]
    entry['changes'] = [{'path': path, 'before': 'Old prose', 'after': 'Reviewed prose'}]
    validate_manifest(document)
    entry['changes'][0]['after'] = {'unreviewed': 'object'}
    with pytest.raises(PatchConflict, match='strings'):
        validate_manifest(document)


def test_applied_final_review_records_each_exact_manifest_trace():
    review = json.loads((ROOT / 'CONTENT_FINAL_THEORY_REVIEW_20261120.json').read_text())
    assert review['source_changes_applied'] is True and review['database_access'] is False
    assert len(review['findings']) == 10
    assert sum(len(finding['proposed_changes']) for finding in review['findings']) == 12
    for finding in review['findings']:
        trace = finding['applied_trace']
        document = json.loads((ROOT / trace['manifest']).read_text())
        entry = next(entry for entry in document['entries'] if entry['file'] == finding['file'])
        for proposed in finding['proposed_changes']:
            change = next(change for change in entry['changes'] if change['path'] == proposed['path'])
            assert change['before'] == proposed['before']
            assert change['after'] == proposed['proposed_after']
        assert trace['after_file_sha256'] == entry['after_file_sha256']
