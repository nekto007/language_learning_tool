"""The recap source patch must be narrow, idempotent and fail closed on drift."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import patch_mobile_grammar_recaps as patch


def fixture_entry(folder, number=1):
    document = {'module': {'level': 'A1', 'id': number, 'order': number, 'title': 'Local fixture', 'lessons': [
        {'id': 42, 'order': 3, 'type': 'grammar', 'content': {
            'external_key': f'curriculum:grammar:A1:{number:02}:fixture',
            'tldr': ['Old summary'], 'rule': 'Preserve this rule',
            'sections': [{'subtitle': 'A section', 'description': 'An existing explanation', 'table': [
                {'example': 'She works here.', 'audio': '[sound:existing.mp3]'}]}],
            'exercises': [{'id': 100, 'type': 'fill_blank', 'question': 'She ___ here.', 'answer': 'works'}],
        }},
        {'id': 43, 'order': 4, 'type': 'reading', 'content': {'text': 'Do not change me'}},
    ]}}
    file = f'module_A1_{number}_fixture.json'
    path = folder / file
    before = (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode()
    path.write_bytes(before)
    after_lines = ['<strong>One rule</strong>: <em>She works here.</em>', 'A second clear rule.', 'A third clear rule.']
    after_document = deepcopy(document)
    after_document['module']['lessons'][0]['content']['tldr'] = after_lines
    neutral = deepcopy(document)
    neutral['module']['lessons'][0]['content']['tldr'] = {'__mobile_recap_patch_field__': True}
    entry = {
        'file': file, 'level': 'A1', 'module_order': number, 'lesson_external_key': f'curriculum:grammar:A1:{number:02}:fixture',
        'before_file_sha256': hashlib.sha256(before).hexdigest(),
        'after_file_sha256': hashlib.sha256((json.dumps(after_document, ensure_ascii=False, indent=2) + '\n').encode()).hexdigest(),
        'unchanged_sha256': patch.semantic_digest(neutral),
        'changes': [{'path': ['tldr'], 'before': ['Old summary'], 'after': after_lines}],
    }
    return path, entry, before


def manifest(*entries):
    return {'schema_version': 1, 'entries': list(entries)}


def test_dry_run_never_writes_and_apply_changes_only_reviewed_field(tmp_path):
    path, entry, before = fixture_entry(tmp_path)
    plan = patch.build_plan(tmp_path, manifest(entry))
    assert path.read_bytes() == before
    assert plan[0].report()['after_sha256'] == entry['after_file_sha256']
    patch.apply_plan(plan)
    actual = json.loads(path.read_bytes())
    expected = json.loads(before)
    expected['module']['lessons'][0]['content']['tldr'] = entry['changes'][0]['after']
    assert actual == expected
    assert patch.build_plan(tmp_path, manifest(entry))[0].state == 'already_applied'


def test_second_apply_does_not_rewrite_a_file_and_rollback_restores_source(tmp_path):
    path, entry, before = fixture_entry(tmp_path)
    patch.apply_plan(patch.build_plan(tmp_path, manifest(entry)))
    stat = path.stat()
    patch.apply_plan(patch.build_plan(tmp_path, manifest(entry)))
    assert path.stat().st_mtime_ns == stat.st_mtime_ns
    patch.apply_plan(patch.build_plan(tmp_path, manifest(entry), rollback=True))
    assert path.read_bytes() == before
    assert patch.build_plan(tmp_path, manifest(entry), rollback=True)[0].state == 'already_restored'


@pytest.mark.parametrize('location', ['answer', 'lesson_id', 'audio', 'new_tldr'])
def test_changed_exercise_identity_audio_or_reviewed_text_aborts(tmp_path, location):
    path, entry, _ = fixture_entry(tmp_path)
    actual = json.loads(path.read_bytes())
    lesson = actual['module']['lessons'][0]
    if location == 'answer':
        lesson['content']['exercises'][0]['answer'] = 'worked'
    elif location == 'lesson_id':
        lesson['id'] = 999
    elif location == 'audio':
        lesson['content']['sections'][0]['table'][0]['audio'] = '[sound:new.mp3]'
    else:
        lesson['content']['tldr'] = ['A newer author edit']
    path.write_text(json.dumps(actual))
    modified = path.read_bytes()
    with pytest.raises(patch.PatchConflict):
        patch.build_plan(tmp_path, manifest(entry))
    assert path.read_bytes() == modified


def test_preflight_of_all_files_happens_before_any_update(tmp_path):
    path1, entry1, before1 = fixture_entry(tmp_path, 1)
    path2, entry2, _ = fixture_entry(tmp_path, 2)
    path2.write_text('{}')
    with pytest.raises(patch.PatchConflict):
        patch.apply_plan(patch.build_plan(tmp_path, manifest(entry1, entry2)))
    assert path1.read_bytes() == before1


def test_source_changed_after_preflight_is_not_overwritten(tmp_path):
    path, entry, _ = fixture_entry(tmp_path)
    plan = patch.build_plan(tmp_path, manifest(entry))
    newer = path.read_bytes() + b'\n'
    path.write_bytes(newer)
    with pytest.raises(patch.PatchConflict):
        patch.apply_plan(plan)
    assert path.read_bytes() == newer


@pytest.mark.parametrize('field', ['../outside.json', 'module_A1_1_fixture.json/../../outside', '/tmp/outside.json'])
def test_manifest_cannot_escape_source_directory(tmp_path, field):
    _, entry, _ = fixture_entry(tmp_path)
    entry['file'] = field
    with pytest.raises(patch.PatchConflict):
        patch.build_plan(tmp_path, manifest(entry))


def test_symlinked_source_is_rejected(tmp_path):
    path, entry, _ = fixture_entry(tmp_path)
    other = tmp_path / 'other.json'
    path.rename(other)
    path.symlink_to(other)
    with pytest.raises(patch.PatchConflict):
        patch.build_plan(tmp_path, manifest(entry))


@pytest.mark.parametrize('changes', [
    [], [{'path': ['exercises'], 'before': [], 'after': []}],
    [{'path': ['tldr'], 'before': [], 'after': ['<em></em>', 'A second rule', 'A third rule']}],
])
def test_unreviewed_fields_and_empty_recaps_are_rejected(tmp_path, changes):
    _, entry, _ = fixture_entry(tmp_path)
    entry['changes'] = changes
    with pytest.raises(patch.PatchConflict):
        patch.build_plan(tmp_path, manifest(entry))


def test_cli_is_dry_run_by_default_and_missing_sources_fail(tmp_path):
    path, entry, before = fixture_entry(tmp_path)
    definition = tmp_path / 'manifest.json'
    definition.write_text(json.dumps(manifest(entry)))
    report = tmp_path / 'report.json'
    assert patch.main(['--source-dir', str(tmp_path), '--manifest', str(definition), '--report', str(report)]) == 0
    assert path.read_bytes() == before
    assert json.loads(report.read_text())['database_access'] is False
    assert patch.main(['--source-dir', str(tmp_path / 'missing'), '--manifest', str(definition)]) == 2


def test_standalone_source_patcher_needs_no_site_packages_or_flask(tmp_path):
    path, entry, before = fixture_entry(tmp_path)
    definition = tmp_path / 'manifest.json'
    definition.write_text(json.dumps(manifest(entry)))
    root = Path(__file__).parents[2]
    result = subprocess.run([sys.executable, '-S', str(root / 'scripts/patch_mobile_grammar_recaps.py'), '--source-dir', str(tmp_path), '--manifest', str(definition)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
    assert 'database access: none' in result.stdout
    assert path.read_bytes() == before


def test_shipped_manifest_has_all_39_reviewed_A1_A2_modules_and_gradeable_examples():
    shipped = json.loads((Path(__file__).parents[2] / 'MOBILE_GRAMMAR_RECAPS_20261120.json').read_text())
    entries = patch.validate_manifest(shipped)
    assert {(e['level'], e['module_order']) for e in entries} == {
        *[('A1', i) for i in range(1, 17)], *[('A2', i) for i in range(1, 24)],
    }
    for entry in entries:
        recap = next(change['after'] for change in entry['changes'] if change['path'] == ['tldr'])
        assert any('<em>' in line for line in recap)
        assert all(len(line) <= 260 for line in recap), entry['file']


def test_example_only_mode_rejects_rewriting_existing_nonempty_rules(tmp_path):
    _, entry, _ = fixture_entry(tmp_path)
    entry['changes'][0]['after'] = [entry['changes'][0]['after'][0]]
    definition = manifest(entry)
    definition['patch_kind'] = 'empty_examples'
    with pytest.raises(patch.PatchConflict, match='nonempty rule'):
        patch.build_plan(tmp_path, definition)


def test_shipped_advanced_patch_fills_19_examples_and_qualifies_15_reviewed_theory_fields():
    definition = json.loads((Path(__file__).parents[2] / 'MOBILE_GRAMMAR_RECAP_EXAMPLES_20261120.json').read_text())
    assert definition['patch_kind'] == 'reviewed_advanced'
    entries = patch.validate_manifest(definition)
    changed = 0
    theory_fields = 0
    for entry in entries:
        theory_fields += sum(change['path'] != ['tldr'] for change in entry['changes'])
        change = next(change for change in entry['changes'] if change['path'] == ['tldr'])
        for evidence in entry['example_evidence']:
            index = evidence['bullet_index']
            assert '<em></em>' in change['before'][index]
            assert evidence['selected_example'] in change['after'][index]
            assert all(path[0] == 'sections' for path in evidence['source_paths'])
            assert len(evidence['source_values']) == len(evidence['source_paths'])
            assert all(isinstance(value, str) and value for value in evidence['source_values'])
        changed += sum(old != new for old,new in zip(change['before'],change['after'],strict=True))
    assert len(entries) == 10 and changed == 19
    assert theory_fields == 15
    assert definition['references']


@pytest.mark.parametrize('path', [['exercises'], ['external_key'], ['sections', 0, 'table', 0, 'audio'], ['important_notes', True]])
def test_advanced_mode_still_rejects_identity_exercise_audio_and_boolean_indexes(tmp_path, path):
    _, entry, _ = fixture_entry(tmp_path)
    entry['changes'].append({'path': path, 'before': 'old', 'after': 'new'})
    definition = manifest(entry)
    definition['patch_kind'] = 'reviewed_advanced'
    with pytest.raises(patch.PatchConflict):
        patch.validate_manifest(definition)
