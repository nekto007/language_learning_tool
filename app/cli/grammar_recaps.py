"""Patch reviewed grammar theory fields without re-importing curriculum or exercises.

The default is a database read-only preflight. Exact lesson external keys and
module identities are mandatory; legacy lessons without keys are unavailable.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
from pathlib import Path

import click
from flask.cli import with_appcontext
from sqlalchemy import select

from app.curriculum.models import CEFRLevel, Lessons, Module
from app.grammar_lab.models import GrammarTopic
from app.utils.db import db
from app.grammar_lab.recap_manifest import PatchConflict, _field, validate_manifest


@dataclass
class RecapReport:
    applied: bool = False
    updates: list[dict] = field(default_factory=list)
    unchanged: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    unavailable: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)

    def as_dict(self):
        return deepcopy(self.__dict__)


@dataclass
class _Update:
    row: object
    before: dict
    after: dict
    detail: dict


def load_manifests(paths):
    """Validate every manifest before consulting the database."""
    entries, identities = [], set()
    for path in paths:
        document = json.loads(Path(path).read_text(encoding='utf-8'))
        for entry in validate_manifest(document):
            identity = (entry['level'], entry['module_order'], entry['lesson_external_key'])
            if identity in identities:
                raise ValueError(f'Duplicate grammar target across manifests: {identity}')
            identities.add(identity)
            normalized = deepcopy(entry)
            normalized['_patch_kind'] = document.get('patch_kind', 'mobile_recaps')
            entries.append(normalized)
    if not entries:
        raise ValueError('No reviewed grammar entries')
    return entries


def _containers(content):
    if not isinstance(content, dict):
        raise ValueError('Content must be a JSON object')
    result = [([], content)]
    if 'grammar_explanation' in content:
        wrapper = content['grammar_explanation']
        if not isinstance(wrapper, dict) or not wrapper:
            raise ValueError('grammar_explanation must be a nonempty JSON object')
        result.append((['grammar_explanation'], wrapper))
    return result


def _read(container, path):
    try:
        parent, key = _field(container, path)
        return True, parent[key]
    except PatchConflict:
        return False, None


def _patched_content(content, changes, *, topic_mirror=False):
    """Require exact reviewed values; update explicit root/wrapped copies only."""
    containers = _containers(content)
    after = deepcopy(content)
    changed = []
    for change in changes:
        target_path = change['path']
        # _grammar_topic_payload explicitly renames description to introduction.
        # This alias applies only to Lab mirrors which omit description entirely.
        # It never masks an unexpected root/wrapper description or introduction.
        alias = False
        if (topic_mirror and target_path == ['description']
                and not any(_read(container, target_path)[0] for _, container in containers)):
            target_path = ['introduction']
            alias = True
        matches = []
        for prefix, container in containers:
            present, current = _read(container, target_path)
            if not present:
                continue
            if current != change['before'] and current != change['after']:
                raise ValueError(f'Unexpected theory field value at {prefix + target_path}')
            matches.append((prefix, current))
        if not matches:
            raise ValueError(f'Reviewed theory field missing: {change["path"]}')
        if len(matches) == 2 and matches[0][1] != matches[1][1]:
            raise ValueError(f'Conflicting root/wrapped copies: {change["path"]}')
        for prefix, current in matches:
            if current == change['before']:
                parent, key = _field(after, prefix + target_path)
                parent[key] = deepcopy(change['after'])
                changed.append(prefix + target_path)
        if topic_mirror and not alias and change['path'] == ['description']:
            # If both legacy names are present, neither may hide stale/drifted
            # prose. Patch identical copies together; reject any disagreement.
            for prefix, container in containers:
                present, introduction = _read(container, ['introduction'])
                if not present:
                    continue
                if introduction != matches[0][1]:
                    raise ValueError('Conflicting description/introduction copies')
                if introduction == change['before']:
                    parent, key = _field(after, [*prefix, 'introduction'])
                    parent[key] = deepcopy(change['after'])
                    changed.append([*prefix, 'introduction'])
    return after, changed


def _lesson_key(content):
    containers = _containers(content)
    keys = [container['external_key'] for _, container in containers if 'external_key' in container]
    if not keys:
        return None
    if any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != 1:
        raise ValueError('Conflicting or invalid lesson external_key')
    return keys[0]


def patch_recaps(session, entries, *, apply=False):
    """Preflight the whole batch and commit only exact reviewed theory fields.

    No rows are created or removed; exercise relations, attempts, progress and
    lesson IDs remain untouched. Missing required lessons block an apply.
    """
    # Entries should come from load_manifests; revalidate identities/field paths
    # even for programmatic callers to avoid bypassing the narrow allowlist.
    identities = set()
    for entry in entries:
        validate_manifest({'schema_version': 1, 'patch_kind': entry.get('_patch_kind', 'mobile_recaps'), 'entries': [entry]})
        identity = (entry['level'], entry['module_order'], entry['lesson_external_key'])
        if identity in identities:
            raise ValueError(f'Duplicate target: {identity}')
        identities.add(identity)
    if not identities:
        raise ValueError('No reviewed grammar entries')
    if apply and (session.new or session.dirty or session.deleted):
        raise ValueError('Refusing to commit unrelated pending database changes')
    report, plan = RecapReport(), []
    with session.no_autoflush:
        for entry in entries:
            identity = {'level': entry['level'], 'module_order': entry['module_order'], 'external_key': entry['lesson_external_key']}
            candidates = session.execute(select(Lessons).join(Module, Lessons.module_id == Module.id).join(CEFRLevel, Module.level_id == CEFRLevel.id).where(CEFRLevel.code == entry['level'], Module.number == entry['module_order'], Lessons.type == 'grammar')).scalars().all()
            matches, bad_key = [], False
            for row in candidates:
                try:
                    if _lesson_key(row.content) == entry['lesson_external_key']:
                        matches.append(row)
                except ValueError as error:
                    bad_key = True
                    report.conflicts.append({**identity, 'target': 'lesson', 'id': row.id, 'reason': str(error)})
            if not matches:
                report.unavailable.append({**identity, 'reason': 'Exact lesson external_key absent; legacy unkeyed content is never guessed'})
            elif len(matches) != 1:
                report.conflicts.append({**identity, 'reason': 'More than one exact grammar lesson'})
            elif not bad_key:
                _plan_row(matches[0], 'lesson', identity, entry, report, plan)
            slug = f"{entry['level'].lower()}-{entry['module_order']}"
            topics = session.execute(select(GrammarTopic).where(GrammarTopic.slug == slug)).scalars().all()
            if not topics:
                report.skipped.append({**identity, 'target': 'topic', 'slug': slug, 'reason': 'Optional conventional GrammarTopic mirror absent'})
            elif len(topics) != 1 or topics[0].level != entry['level']:
                report.conflicts.append({**identity, 'target': 'topic', 'slug': slug, 'reason': 'Conventional mirror level/identity mismatch'})
            else:
                _plan_row(topics[0], 'topic', identity, entry, report, plan)
    if not apply:
        return report
    if report.conflicts or report.unavailable:
        raise ValueError(f'Grammar recap apply refused: {len(report.conflicts)} conflicts, {len(report.unavailable)} unavailable lessons; run dry-run for details')
    try:
        # Lock and refresh every target before the first update. PostgreSQL
        # JSON has no equality operator, so comparing the mapped JSON column
        # in an UPDATE predicate would fail on deployed PostgreSQL lessons.
        # Row locks keep concurrent admin edits from racing the final compare.
        for item in plan:
            model = type(item.row)
            current = session.execute(select(model).where(model.id == item.row.id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
            if current is None or current.content != item.before:
                raise ValueError(f'Content changed after preflight: {item.detail}')
        for item in plan:
            item.row.content = deepcopy(item.after)
        session.commit()
        session.expire_all()
    except Exception:
        session.rollback()
        raise
    report.applied = True
    return report


def _plan_row(row, kind, identity, entry, report, plan):
    detail = {**identity, 'target': kind, 'id': row.id}
    try:
        after, paths = _patched_content(row.content, entry['changes'], topic_mirror=kind == 'topic')
    except ValueError as error:
        report.conflicts.append({**detail, 'reason': str(error)})
        return
    if paths:
        detail['paths'] = paths
        report.updates.append(detail)
        plan.append(_Update(row, deepcopy(row.content), after, detail))
    else:
        report.unchanged.append(detail)


@click.command('grammar-recaps')
@click.argument('manifests', nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option('--apply', 'apply_changes', is_flag=True, help='Apply exact reviewed fields in one transaction')
@click.option('--report', 'report_path', type=click.Path(dir_okay=False, path_type=Path), help='Write detailed preflight report as JSON')
@with_appcontext
def grammar_recaps_command(manifests, apply_changes, report_path):
    """Safely patch reviewed lesson/Lab theory; default is a read-only dry-run."""
    try:
        entries = load_manifests(manifests)
        report = patch_recaps(db.session, entries, apply=apply_changes)
    except (ValueError, OSError) as error:
        raise click.ClickException(str(error)) from error
    if report_path:
        report_path.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    mode = 'APPLIED' if report.applied else 'DRY RUN'
    action = 'rows patched' if report.applied else 'rows to patch'
    click.echo(f'{mode}: {len(report.updates)} {action}, {len(report.unchanged)} unchanged, {len(report.skipped)} optional mirrors skipped, {len(report.unavailable)} unavailable lessons, {len(report.conflicts)} conflicts')
    for status in ('unavailable', 'conflicts', 'skipped'):
        for detail in getattr(report, status):
            click.echo(f'{status}: {json.dumps(detail, ensure_ascii=False)}')
    if not report.applied:
        click.echo('No database changes. Apply refuses unavailable required lessons or unexpected drift.')
