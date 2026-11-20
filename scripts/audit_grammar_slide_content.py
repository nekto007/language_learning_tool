#!/usr/bin/env python3
"""Generate real grammar slide fixtures and audit actual Swift builder output.

Reads local canonical JSON and the existing API projector without Flask startup,
SQL or network. The corpus fixture is generated outside source directories; it
is not a second committed copy of the authored curriculum. --swift-check runs the
real LLTCore XCTest locally and verifies its reconstructed authored fields.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_SUPPLEMENTS = [ROOT / 'MOBILE_GRAMMAR_SUPPLEMENTS_20261120.json', ROOT / 'MOBILE_GRAMMAR_FUTURE_PERFECT_20261120.json']
REFERENCE = ROOT / 'ios/Core/Sources/LLTCore/Resources/GrammarLibrary.json'


def _theory(content):
    # Help and pure result inspection work without the project's Flask stack.
    # Projection itself uses the exact server implementation in the project env.
    from app.api.native_lessons import _theory as project

    return project(content)


def primary_fields(blocks):
    """Source-field specification, independent of pagination or splitting rules.

    Typed table/example metadata is the primary representation. Their server
    body is a redundant legacy fallback and must not be required a second time.
    Text-only/incomplete metadata still requires the complete fallback body.
    """
    expected = {}

    def keep(key, value):
        if isinstance(value, str) and value:
            expected[key] = value

    for index, block in enumerate(blocks):
        prefix = str(index)
        keep(prefix + '.title', block.get('title'))
        table = block.get('table')
        examples = block.get('examples')
        if block.get('kind') == 'table' and isinstance(table, dict) and any(
            any(isinstance(cell, str) and cell.strip() for cell in row) for row in table.get('rows') or []
        ):
            for column, header in enumerate(table.get('headers') or []):
                keep(prefix + f'.header.{column}', header)
            for row_number, row in enumerate(table.get('rows') or []):
                for column, cell in enumerate(row):
                    keep(prefix + f'.row.{row_number}.{column}', cell)
        elif block.get('kind') == 'examples' and isinstance(examples, list) and any(
            any(str(example.get(key) or '').strip() for key in ('english', 'translation', 'explanation'))
            for example in examples if isinstance(example, dict)
        ):
            for number, example in enumerate(examples):
                if not isinstance(example, dict):
                    continue
                for key in ('english', 'translation', 'explanation'):
                    keep(prefix + f'.example.{number}.' + key, example.get(key))
        else:
            keep(prefix + '.body', block.get('body'))
        keep(prefix + '.translation', block.get('translation'))
    return expected


def reference_values(lesson):
    values = [lesson['title'], lesson['introduction']]
    for block in lesson['blocks']:
        values.extend([block['title'], block['body'], *block['examples']])
    return [value for value in values if value]


def generate_fixture(source, supplements, reference):
    cases = []
    for path in sorted(Path(source).glob('*.json')):
        module = json.loads(path.read_text(encoding='utf-8'))['module']
        for lesson in module['lessons']:
            if lesson['type'] != 'grammar':
                continue
            content = lesson['content']
            blocks = _theory(content)
            cases.append({'id': content['external_key'], 'source_kind': 'canonical', 'source': path.name,
                          'level': module['level'], 'title': lesson['title'], 'blocks': blocks,
                          'expected_by_source_key': primary_fields(blocks)})
    if not cases:
        raise ValueError('No canonical grammar sources; an empty corpus cannot pass')
    for path in supplements:
        for topic in json.loads(Path(path).read_text(encoding='utf-8'))['topics']:
            blocks = _theory(topic['content'])
            cases.append({'id': topic['slug'], 'source_kind': 'supplement', 'source': Path(path).name,
                          'level': topic['level'], 'title': topic['title_ru'], 'blocks': blocks,
                          'expected_by_source_key': primary_fields(blocks)})
    for lesson in json.loads(Path(reference).read_text(encoding='utf-8')):
        cases.append({'id': 'reference:' + lesson['id'], 'source_kind': 'reference', 'source': Path(reference).name,
                      'level': lesson['level'], 'title': lesson['title'], 'reference_lesson': lesson,
                      'expected_values': reference_values(lesson)})
    ids = [case['id'] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate topic identity in slide audit fixture')
    return {'schema_version': 1, 'budget': 350, 'compact_budget': 180, 'cases': cases}


def verify_result(fixture, output):
    """Check emitted Swift strings/IDs against original fixture expectations."""
    failures = []
    actual = output.get('cases')
    if not isinstance(actual, list):
        return [{'error': 'Swift result has no cases'}]
    by_id = {case.get('id'): case for case in actual}
    if len(by_id) != len(actual) or set(by_id) != {case['id'] for case in fixture['cases']}:
        failures.append({'error': 'Swift case identities differ from generated source fixture'})
    for source in fixture['cases']:
        case = by_id.get(source['id'])
        if case is None:
            continue
        identity = {'id': source['id'], 'source': source['source']}
        reconstructed = case.get('actual_by_source_key')
        if not isinstance(reconstructed, dict):
            failures.append({**identity, 'error': 'Missing reconstructed source strings'})
            continue
        if source['source_kind'] == 'reference':
            missing = Counter(source['expected_values']) - Counter(reconstructed.values())
            if missing:
                failures.append({**identity, 'error': 'Reference adapter lost authored values', 'missing': dict(missing)})
        elif reconstructed != source['expected_by_source_key']:
            expected = source['expected_by_source_key']
            failures.append({**identity, 'error': 'Projected authored field loss/change/duplication',
                             'changed_keys': [key for key in set(expected) | set(reconstructed)
                                              if expected.get(key) != reconstructed.get(key)]})
        ids = case.get('slide_ids') or []
        if (not ids or ids != case.get('repeat_slide_ids') or len(ids) != len(set(ids))
                or len(ids) != case.get('slide_count')):
            failures.append({**identity, 'error': 'Unstable, empty or duplicated slide identity'})
        if case.get('fingerprint') != case.get('repeat_fingerprint') or not case.get('fingerprint'):
            failures.append({**identity, 'error': 'Unstable or absent deck fingerprint'})
        if not 0 < case.get('max_characters', 0) <= fixture['budget']:
            failures.append({**identity, 'error': 'Slide exceeds default character budget'})
        if not 0 < case.get('compact_max_characters', 0) <= fixture['compact_budget']:
            failures.append({**identity, 'error': 'Slide exceeds compact character budget'})
        if case.get('compact_lossless') is not True:
            failures.append({**identity, 'error': 'Compact budget loses authored source fields'})
        parts = case.get('part_slide_ids')
        if (not isinstance(parts, list) or not parts or any(not isinstance(part, list) or not 0 < len(part) <= 8 for part in parts)
                or [slide for part in parts for slide in part] != ids or parts != case.get('repeat_part_slide_ids')):
            failures.append({**identity, 'error': 'Short study parts omit, repeat, reorder or exceed eight slides'})
    return failures


def report_lines(fixture, result=None, failures=None):
    cases = fixture['cases']
    server = [case for case in cases if case['source_kind'] != 'reference']
    blocks = [(case, number, block) for case in server for number, block in enumerate(case['blocks'])]
    kinds = Counter(block.get('kind', 'legacy') for _, _, block in blocks)
    tables = [(case, number, block['table']) for case, number, block in blocks if block.get('table')]
    duplicate_titles = sum(len(case['blocks']) - len({block['title'] for block in case['blocks']}) for case in server)
    longest = max(blocks, key=lambda item: len(item[2]['body']))
    longest_cell = max(((len(cell), case['id'], block, row, column)
                        for case, block, table in tables for row, cells in enumerate(table['rows'])
                        for column, cell in enumerate(cells)), default=(0, '', 0, 0, 0))
    lines = [
        'GRAMMAR_SLIDE_CONTENT_AUDIT',
        'canonical_topics=' + str(sum(case['source_kind'] == 'canonical' for case in cases)),
        'supplement_topics=' + str(sum(case['source_kind'] == 'supplement' for case in cases)),
        'reference_topics=' + str(sum(case['source_kind'] == 'reference' for case in cases)),
        'server_blocks=' + str(len(blocks)), 'server_block_kinds=' + json.dumps(dict(kinds), sort_keys=True),
        'structured_tables=' + str(len(tables)),
        'structured_table_rows=' + str(sum(len(table['rows']) for _, _, table in tables)),
        'max_table_columns=' + str(max((len(table['headers']) for _, _, table in tables), default=0)),
        'duplicate_titles_within_topics=' + str(duplicate_titles),
        'longest_legacy_body_codepoints=' + str(len(longest[2]['body'])),
        'longest_legacy_body_topic=' + longest[0]['id'],
        'longest_cell_codepoints=' + str(longest_cell[0]), 'longest_cell_topic=' + longest_cell[1],
        'default_swift_character_budget=' + str(fixture['budget']),
        'compact_swift_character_budget=' + str(fixture['compact_budget']),
        'builder_sha256=' + hashlib.sha256((ROOT / 'ios/Core/Sources/LLTCore/GrammarSlides.swift').read_bytes()).hexdigest(),
        'fixture_payload_sha256=' + hashlib.sha256(json.dumps(fixture, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        'database_access=false', 'source_changes=false',
    ]
    if result is not None:
        lines.append('swift_result_payload_sha256=' + hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
        rows = result.get('cases') or []
        by_id = {case['id']: case for case in cases}
        histogram = Counter(f'{((case["slide_count"] - 1) // 10) * 10 + 1:02}-{((case["slide_count"] - 1) // 10 + 1) * 10:02}' for case in rows)
        slide_kinds = Counter()
        named_blocks = Counter()
        for case in rows:
            slide_kinds.update(case.get('slide_kind_counts') or {})
            original = by_id.get(case['id'], {})
            for index, block in enumerate(original.get('blocks') or []):
                named_blocks[block['title']] += (case.get('source_block_slide_counts') or {}).get(str(index), 0)
        lines += ['actual_swift_cases=' + str(len(rows)),
                  'actual_slides=' + str(sum(case.get('slide_count', 0) for case in rows)),
                  'actual_max_characters=' + str(max((case.get('max_characters', 0) for case in rows), default=0)),
                  'actual_max_slides_per_topic=' + str(max((case.get('slide_count', 0) for case in rows), default=0)),
                  'slide_count_histogram=' + json.dumps(dict(sorted(histogram.items())), sort_keys=True),
                  'slide_kind_counts=' + json.dumps(dict(slide_kinds), sort_keys=True),
                  'authored_characters=' + str(sum(case.get('authored_characters', 0) for case in rows)),
                  'repeated_context_characters=' + str(sum(case.get('repeated_context_characters', 0) for case in rows)),
                  'additional_vocabulary_slides=' + str(named_blocks['Дополнительные примеры со словарём модуля']),  # noqa: RUF001
                  'summary_slides=' + str(named_blocks['Итоги']),
                  'recap_slides=' + str(named_blocks['Коротко']),
                  'study_parts=' + str(sum(len(case.get('part_slide_ids') or []) for case in rows)),
                  'max_slides_per_study_part=' + str(max((len(part) for case in rows for part in case.get('part_slide_ids') or []), default=0)),
                  'failures=' + str(len(failures or [])),
                  'result=' + ('PASS' if not failures else 'FAIL')]
        for case in sorted(rows, key=lambda item: item.get('slide_count', 0), reverse=True)[:10]:
            lines.append('largest_topic=' + json.dumps({'id': case['id'], 'title': by_id.get(case['id'], {}).get('title'),
                                                        'slides': case.get('slide_count')}, ensure_ascii=False, sort_keys=True))
        for failure in failures or []:
            lines.append('failure=' + json.dumps(failure, ensure_ascii=False, sort_keys=True))
    else:
        lines.append('result=FIXTURE_GENERATED_NOT_SWIFT_VERIFIED')
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'module_completed/fixed')
    parser.add_argument('--supplement', type=Path, action='append', help='Defaults to the two reviewed supplemental seed packs')
    parser.add_argument('--reference', type=Path, default=REFERENCE)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True, help='Data-only TXT audit report')
    parser.add_argument('--swift-result', type=Path, help='Verify an existing actual Swift test result')
    parser.add_argument('--swift-check', action='store_true', help='Run the actual LLTCore corpus test')
    args = parser.parse_args(argv)
    report_safe = False
    try:
        result_path = args.swift_result
        if args.swift_check:
            result_path = result_path or args.fixture.with_suffix('.slides.json')
        inputs = [args.source.resolve(), args.reference.resolve(), *[path.resolve() for path in args.supplement or DEFAULT_SUPPLEMENTS]]
        for path in (args.fixture, args.report, result_path):
            if path and any(path.resolve() == item or (item.is_dir() and item in path.resolve().parents) for item in inputs):
                raise ValueError('Audit outputs must be outside authored sources')
        outputs = [path.resolve() for path in (args.fixture, args.report, result_path) if path]
        if len(outputs) != len(set(outputs)):
            raise ValueError('Fixture, report and Swift result paths must be distinct')
        report_safe = True
        fixture = generate_fixture(args.source, args.supplement or DEFAULT_SUPPLEMENTS, args.reference)
        args.fixture.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        args.report.write_text('\n'.join(report_lines(fixture)) + '\n', encoding='utf-8')
        if args.swift_check:
            if result_path.exists():
                result_path.unlink()
            cache = Path(tempfile.gettempdir()) / 'llt-grammar-slide-module-cache'
            cache.mkdir(exist_ok=True)
            env = {**os.environ, 'LLT_GRAMMAR_SLIDE_CORPUS_FIXTURE': str(args.fixture.resolve()),
                   'LLT_GRAMMAR_SLIDE_AUDIT_OUTPUT': str(result_path.resolve()),
                   'CLANG_MODULE_CACHE_PATH': str(cache), 'SWIFT_MODULECACHE_PATH': str(cache)}
            completed = subprocess.run(['swift', 'test', '--package-path', str(ROOT / 'ios/Core'),
                                        '--scratch-path', str(Path(tempfile.gettempdir()) / 'llt-grammar-slide-audit-build'),
                                        '--filter', 'GrammarSlideCorpusAuditTests'], cwd=ROOT, env=env, check=False)
            if completed.returncode != 0:
                raise ValueError('Actual Swift corpus test failed')
        result = json.loads(result_path.read_text(encoding='utf-8')) if result_path else None
        failures = verify_result(fixture, result) if result is not None else None
        lines = report_lines(fixture, result, failures)
        args.report.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print('\n'.join(lines))
        return 1 if failures else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        if report_safe:
            with suppress(OSError):
                args.report.write_text('GRAMMAR_SLIDE_CONTENT_AUDIT\nresult=FAIL\nerror=' + str(error) + '\n', encoding='utf-8')
        print(f'FAIL: {error}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
