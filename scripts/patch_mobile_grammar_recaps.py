#!/usr/bin/env python3
"""Apply the reviewed, source-only mobile grammar recap patch.

Default invocation is read-only. No Flask import, credentials, network, SQL or
production database are used. All entries are preflighted before any write.
Unrelated source content must match the manifest's contextual SHA-256.

    python scripts/patch_mobile_grammar_recaps.py
    python scripts/patch_mobile_grammar_recaps.py --apply --report /tmp/recaps.json
    python scripts/patch_mobile_grammar_recaps.py --rollback

A deliberate rollback restores only reviewed fields; it refuses newer changes.
Publish reviewed theory fields with the separate Flask grammar-recaps command,
following GRAMMAR_MOBILE_ROLLOUT_20261120.txt. Do not re-import curriculum or
exercises for these corrections. This source script never accesses a live DB.
"""
from __future__ import annotations

import argparse
import importlib.util
import copy
import hashlib
import json
import os
import tempfile
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / 'MOBILE_GRAMMAR_RECAPS_20261120.json'
DEFAULT_SOURCE = ROOT / 'module_completed' / 'fixed'
# Load the shared stdlib-only module by filename. A normal app.* import would
# execute app/__init__.py and require Flask even for a read-only source patch.
_SPEC = importlib.util.spec_from_file_location('_llt_recap_manifest', ROOT / 'app' / 'grammar_lab' / 'recap_manifest.py')
_SHARED = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _SHARED
_SPEC.loader.exec_module(_SHARED)
PatchConflict = _SHARED.PatchConflict
semantic_digest = _SHARED.semantic_digest
_field = _SHARED._field
validate_manifest = _SHARED.validate_manifest
_MARKER = _SHARED._MARKER


@dataclass(frozen=True)
class PlannedFile:
    path: Path
    state: str
    before: bytes
    after: bytes
    changed_fields: int

    def report(self) -> dict[str, Any]:
        return {
            'file': self.path.name,
            'state': self.state,
            'changed_fields': self.changed_fields,
            'before_sha256': hashlib.sha256(self.before).hexdigest(),
            'after_sha256': hashlib.sha256(self.after).hexdigest(),
        }


def _lesson(document: Any, entry: dict) -> dict:
    module = document.get('module') if isinstance(document, dict) else None
    if (not isinstance(module, dict) or module.get('level') != entry['level']
            or (module.get('order') or module.get('id')) != entry['module_order']):
        raise PatchConflict(f'Module identity changed: {entry["file"]}')
    lessons = [lesson for lesson in module.get('lessons', [])
               if isinstance(lesson, dict) and lesson.get('type') == 'grammar'
               and isinstance(lesson.get('content'), dict)
               and lesson['content'].get('external_key') == entry['lesson_external_key']]
    if len(lessons) != 1:
        raise PatchConflict(f'Grammar lesson identity is absent or ambiguous: {entry["file"]}')
    return lessons[0]


def build_plan(source: Path, manifest: dict, *, rollback: bool = False) -> list[PlannedFile]:
    """Read and check every file; return a complete plan without changing any."""
    entries = validate_manifest(manifest)
    result = []
    source = source.resolve()
    if not source.is_dir():
        raise PatchConflict(f'Source directory does not exist: {source}')
    for entry in entries:
        path = source / entry['file']
        if path.is_symlink() or not path.is_file():
            raise PatchConflict(f'Source file missing or symlinked: {path}')
        before = path.read_bytes()
        try:
            document = json.loads(before)
        except (ValueError, UnicodeDecodeError) as error:
            raise PatchConflict(f'Invalid source JSON: {path.name}') from error
        lesson = _lesson(document, entry)
        neutral = copy.deepcopy(document)
        neutral_content = _lesson(neutral, entry)['content']
        states = []
        for change in entry['changes']:
            container, key = _field(lesson['content'], change['path'])
            current = container[key]
            if current == change['before']:
                states.append('before')
            elif current == change['after']:
                states.append('after')
            else:
                raise PatchConflict(f'Reviewed field changed: {path.name}: {change["path"]}')
            container, key = _field(neutral_content, change['path'])
            container[key] = _MARKER
        if semantic_digest(neutral) != entry['unchanged_sha256']:
            raise PatchConflict(f'Unrelated source content changed: {path.name}')
        if len(set(states)) != 1:
            raise PatchConflict(f'Partial prior patch detected: {path.name}; review it before continuing')
        desired = 'before' if rollback else 'after'
        if states[0] == desired:
            result.append(PlannedFile(path, 'already_restored' if rollback else 'already_applied', before, before, 0))
            continue
        for change in entry['changes']:
            container, key = _field(lesson['content'], change['path'])
            container[key] = copy.deepcopy(change['before' if rollback else 'after'])
        after = (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode()
        result.append(PlannedFile(path, 'restore' if rollback else 'update', before, after, len(entry['changes'])))
    return result


def apply_plan(plan: list[PlannedFile]) -> None:
    """Recheck the whole preflight, then atomically replace individual files."""
    for item in plan:
        if item.path.is_symlink() or item.path.read_bytes() != item.before:
            raise PatchConflict(f'Source changed after preflight: {item.path.name}')
    written = []
    try:
        for item in plan:
            if item.before == item.after:
                continue
            _atomic_write(item.path, item.after)
            written.append(item)
    except OSError:
        # Recover the files already written; never leave an intentional partial
        # rollout when a later disk write fails. Original data is in memory.
        for item in reversed(written):
            _atomic_write(item.path, item.before)
        raise


def _atomic_write(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name + '.', delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            temporary.chmod(path.stat().st_mode & 0o777)
            handle.close()
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source-dir', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Apply reviewed recap fields to local source JSON')
    mode.add_argument('--rollback', action='store_true', help='Restore reviewed fields in local source JSON')
    parser.add_argument('--report', type=Path, help='Write before/after SHA-256 and states as JSON')
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text())
        plan = build_plan(args.source_dir, manifest, rollback=args.rollback)
        if args.apply or args.rollback:
            apply_plan(plan)
        report = {'mode': 'rollback' if args.rollback else 'apply' if args.apply else 'dry_run',
                  'files': [item.report() for item in plan], 'database_access': False}
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        changed = sum(item.before != item.after for item in plan)
        print(f'{report["mode"]}: {len(plan)} reviewed files, {changed} to change; database access: none')
        for item in plan:
            print(f'  {item.state:17} {item.path.name} ({item.changed_fields} fields)')
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(f'ABORT: {error}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
