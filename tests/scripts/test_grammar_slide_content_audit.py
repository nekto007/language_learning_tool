"""The slide audit compares authored fields, not a second pagination algorithm."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

from scripts import audit_grammar_slide_content as audit


def test_help_runs_without_importing_the_project_dependency_stack():
    result = subprocess.run(
        [sys.executable, "-S", str(Path(audit.__file__)), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "--swift-check" in result.stdout and "--fixture" in result.stdout


def test_primary_fields_preserve_structured_cells_and_legacy_fallback_without_double_counting():
    blocks = [
        {'title': 'Same title', 'kind': 'table', 'body': 'redundant legacy table rendering',
         'table': {'headers': ['English', 'Русский'], 'rows': [['one\nline', 'первая строка'], ['two', 'вторая']]},
         'translation': 'whole block translation'},
        {'title': 'Same title', 'kind': 'examples', 'body': 'redundant combined example rendering',
         'examples': [{'english': 'I am here.', 'translation': 'Я здесь.', 'explanation': 'I + am'}]},
        {'title': 'Incomplete optional table', 'kind': 'table', 'body': 'Must keep this fallback.',
         'table': {'headers': [], 'rows': []}},
    ]
    fields = audit.primary_fields(blocks)
    assert fields['0.row.0.0'] == 'one\nline'
    assert fields['0.header.1'] == 'Русский'
    assert fields['0.translation'] == 'whole block translation'
    assert fields['1.example.0.english'] == 'I am here.'
    assert fields['1.example.0.translation'] == 'Я здесь.'
    assert fields['1.example.0.explanation'] == 'I + am'
    assert fields['2.body'] == 'Must keep this fallback.'
    assert '0.body' not in fields and '1.body' not in fields
    assert fields['0.title'] == fields['1.title'] == 'Same title'


def baseline():
    source = {'id': 'actual-topic', 'source': 'fixture.json', 'source_kind': 'canonical',
              'expected_by_source_key': {'0.title': 'A rule', '0.body': 'Keep every character, including spaces. '}}
    fixture = {'budget': 350, 'compact_budget': 180, 'cases': [source]}
    result = {'cases': [{'id': source['id'], 'fingerprint': 'stable', 'repeat_fingerprint': 'stable',
                         'slide_ids': ['stable:0'], 'repeat_slide_ids': ['stable:0'], 'slide_count': 1,
                         'max_characters': 51, 'compact_max_characters': 51, 'compact_lossless': True,
                         'part_slide_ids': [['stable:0']], 'repeat_part_slide_ids': [['stable:0']],
                         'actual_by_source_key': deepcopy(source['expected_by_source_key'])}]}
    return fixture, result


def test_verifier_rejects_changed_authored_text_duplicate_ids_and_budget_overflow():
    fixture, result = baseline()
    assert audit.verify_result(fixture, result) == []
    result['cases'][0]['actual_by_source_key']['0.body'] = 'A summary that loses the original.'
    assert any('field loss' in row['error'] for row in audit.verify_result(fixture, result))
    fixture, result = baseline()
    result['cases'][0]['repeat_slide_ids'] = ['different:0']
    assert any('identity' in row['error'] for row in audit.verify_result(fixture, result))
    fixture, result = baseline()
    result['cases'][0]['max_characters'] = 351
    assert any('budget' in row['error'] for row in audit.verify_result(fixture, result))


def test_short_study_parts_must_cover_all_slides_once_in_order():
    fixture, result = baseline()
    result['cases'][0]['part_slide_ids'] = [['stable:0', 'stable:0']]
    assert any('study parts' in row['error'] for row in audit.verify_result(fixture, result))
    result['cases'][0]['part_slide_ids'] = []
    assert any('study parts' in row['error'] for row in audit.verify_result(fixture, result))


def test_reference_original_body_and_repeated_headings_cannot_be_lost_in_adapter():
    fixture, result = baseline()
    fixture['cases'][0].update(source_kind='reference', expected_values=['Same title', 'Same title', 'Original body'])
    result['cases'][0]['actual_by_source_key'] = {'0.title': 'Same title', '0.body': 'Original body'}
    assert any('Reference adapter' in row['error'] for row in audit.verify_result(fixture, result))
    result['cases'][0]['actual_by_source_key']['1.title'] = 'Same title'
    assert audit.verify_result(fixture, result) == []


def test_generated_fixture_uses_real_server_projection_and_preserves_original_reference(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    path = source / 'module_A1_1_fixture.json'
    path.write_text(json.dumps({'module': {'level': 'A1', 'lessons': [{'type': 'grammar', 'title': 'A rule', 'content': {
        'external_key': 'course:1', 'rule': 'I am; we are.', 'sections': [{'subtitle': 'Forms', 'table': [
            {'pronoun': 'I', 'verb': 'am', 'example': 'I am here.', 'translation': 'Я здесь.'}]}],
    }}]}}))
    reference = tmp_path / 'reference.json'
    original = [{'id': 'book:1', 'title': 'Book rule', 'level': 'A1', 'introduction': 'Original introduction.',
                 'blocks': [{'title': 'Notes', 'body': 'Original body.', 'examples': ['A · B'] }]}]
    reference.write_text(json.dumps(original))
    before = path.read_bytes()
    fixture = audit.generate_fixture(source, [], reference)
    assert len(fixture['cases']) == 2
    projected = fixture['cases'][0]
    assert 'I am; we are.' in projected['expected_by_source_key'].values()
    assert any(key.endswith('.row.0.2') for key in projected['expected_by_source_key'])
    bundled = fixture['cases'][1]
    assert bundled['reference_lesson'] == original[0]
    assert bundled['expected_values'] == ['Book rule', 'Original introduction.', 'Notes', 'Original body.', 'A · B']
    assert path.read_bytes() == before
