"""Stdlib-only validation for reviewed source and database theory patches.

The same narrow field allowlist is shared by the standalone source patcher and
Flask rollout. Importing this module itself requires no database or network.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_MARKER = {'__mobile_recap_patch_field__': True}
_SHA = re.compile(r'^[a-f0-9]{64}$')
_FILENAME = re.compile(r'^module_(A1|A2|B1|B2|C1)_([1-9][0-9]*)_[a-z0-9_]+\.json$')


class PatchConflict(ValueError):
    """A manifest or source no longer matches the reviewed patch."""


def semantic_digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def _field(container: dict, path: list[str | int]) -> tuple[Any, str | int]:
    current: Any = container
    try:
        for key in path[:-1]:
            current = current[key]
        current[path[-1]]  # Refuse creation of unreviewed fields.
    except (KeyError, IndexError, TypeError) as error:
        raise PatchConflict(f'Missing reviewed content field: {path}') from error
    return current, path[-1]


def _display_note_path(path: Any) -> bool:
    """Only reviewed scalar teaching prose, never media, IDs or answer keys."""
    if not isinstance(path, list):
        return False

    def index(value):
        return type(value) is int and value >= 0

    return (
        (len(path) == 2 and path[0] == 'important_notes' and index(path[1]))
        or (len(path) == 4 and path[0] == 'sections' and index(path[1])
            and path[2] == 'notes' and index(path[3]))
        or (len(path) == 5 and path[0] == 'sections' and index(path[1])
            and path[2] == 'table' and index(path[3]) and path[4] in ('note', 'form'))
        or (len(path) == 4 and path[:2] == ['summary', 'table'] and index(path[2])
            and path[3] in ('example', 'translation'))
    )


def _allowed_path(path: Any, *, advanced: bool = False) -> bool:
    if _display_note_path(path):
        return True
    if advanced and isinstance(path, list):
        def index(value):
            return type(value) is int and value >= 0
        if path in (['rule'], ['description'], ['summary', 'note']):
            return True
        if len(path) == 2 and path[0] == 'important_notes' and index(path[1]):
            return True
        if len(path) >= 5 and path[0] == 'sections' and index(path[1]) and index(path[3]):
            if path[2] == 'table' and len(path) == 5 and path[4] in (
                    'wrong', 'explanation', 'subject', 'form', 'embedded', 'translation'):
                return True
            if path[2] == 'rules':
                if len(path) == 5 and path[4] == 'rule':
                    return True
                if len(path) == 6 and path[4] == 'examples' and index(path[5]):
                    return True
    return path == ['tldr'] or (
        isinstance(path, list) and len(path) == 3 and path[0] == 'sections'
        and type(path[1]) is int and path[1] >= 0 and path[2] in ('subtitle', 'description')
    )


def validate_manifest(manifest: Any) -> list[dict]:
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
            or manifest['schema_version'] != 1):
        raise PatchConflict('Unsupported or missing manifest schema_version')
    entries = manifest.get('entries')
    kind = manifest.get('patch_kind', 'mobile_recaps')
    if kind not in ('mobile_recaps', 'empty_examples', 'reviewed_advanced', 'advanced_recaps'):
        raise PatchConflict('Unsupported patch_kind')
    if not isinstance(entries, list) or not entries:
        raise PatchConflict('Manifest has no reviewed entries')
    seen = set()
    identities = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise PatchConflict('Manifest entry must be an object')
        filename = entry.get('file')
        match = _FILENAME.fullmatch(filename) if isinstance(filename, str) else None
        if not match or filename in seen:
            raise PatchConflict(f'Invalid or repeated source filename: {filename}')
        seen.add(filename)
        identity = (entry.get('level'), entry.get('module_order'))
        if (identity in identities or identity != (match[1], int(match[2]))
                or type(entry.get('module_order')) is not int):
            raise PatchConflict(f'Invalid or repeated module identity: {filename}')
        identities.add(identity)
        if not isinstance(entry.get('lesson_external_key'), str) or not entry['lesson_external_key']:
            raise PatchConflict(f'Missing lesson identity: {filename}')
        for name in ('before_file_sha256', 'after_file_sha256', 'unchanged_sha256'):
            if not isinstance(entry.get(name), str) or not _SHA.fullmatch(entry[name]):
                raise PatchConflict(f'Invalid {name}: {filename}')
        changes = entry.get('changes')
        if not isinstance(changes, list) or not changes:
            raise PatchConflict(f'No reviewed changes: {filename}')
        theory_only = entry.get('theory_only', False)
        if type(theory_only) is not bool or (theory_only and kind != 'advanced_recaps'):
            raise PatchConflict(f'Theory-only entries require the explicit advanced kind: {filename}')
        paths = set()
        for change in changes:
            if not isinstance(change, dict) or set(change) != {'path', 'before', 'after'}:
                raise PatchConflict(f'Invalid change: {filename}')
            path = change['path']
            if not _allowed_path(path, advanced=kind in ('reviewed_advanced', 'advanced_recaps')) or tuple(path) in paths:
                raise PatchConflict(f'Unreviewed or duplicate field: {filename}: {path}')
            paths.add(tuple(path))
            if path == ['tldr']:
                after = change['after']
                if (not isinstance(after, list) or not after
                        or (kind in ('mobile_recaps', 'advanced_recaps') and not 3 <= len(after) <= 5)
                        or any(not isinstance(line, str) or not line.strip() for line in after)
                        or any(re.search(r'<(?:em|strong)>\s*</(?:em|strong)>', line) for line in after)):
                    raise PatchConflict(f'Invalid mobile recap: {filename}')
                if kind in ('empty_examples', 'reviewed_advanced'):
                    _validate_example_only_change(change, filename)
            elif not isinstance(change['before'], str) or not isinstance(change['after'], str):
                raise PatchConflict(f'Theory descriptions must remain strings: {filename}')
            elif kind == 'empty_examples':
                raise PatchConflict(f'Example-only patch cannot alter theory descriptions: {filename}')
            elif not change['after'].strip():
                raise PatchConflict(f'Theory descriptions cannot be empty: {filename}')
        if theory_only and (('tldr',) in paths or any(not _display_note_path(change['path']) for change in changes)):
            raise PatchConflict(f'Theory-only entries may only correct reviewed display notes: {filename}')
        if ('tldr',) not in paths and not theory_only:
            raise PatchConflict(f'Missing tldr change: {filename}')
    return entries


def _validate_example_only_change(change: dict, filename: str) -> None:
    before, after = change['before'], change['after']
    if not isinstance(before, list) or len(before) != len(after):
        raise PatchConflict(f'Example-only patch cannot add/remove recap bullets: {filename}')
    edits = 0
    for old, new in zip(before, after, strict=True):
        if old == new:
            continue
        match = re.fullmatch(r'(.*<em>)\s*(</em>.*)', old) if isinstance(old, str) else None
        if not match or not new.startswith(match[1]) or not new.endswith(match[2]):
            raise PatchConflict(f'Example-only patch changed a nonempty rule: {filename}')
        example = new[len(match[1]):-len(match[2])]
        if not example.strip() or '<' in example or '>' in example:
            raise PatchConflict(f'Invalid replacement example: {filename}')
        edits += 1
    if not edits:
        raise PatchConflict(f'Example-only patch has no empty examples to fill: {filename}')
