"""Rewrite legacy slug prerequisites into the form the parser actually reads.

Audit CNT-014 (cross-zone audit 2026-08-08). Two modules carry authored
prerequisites as level-relative slug strings:

    A1 M4  -> ["module_1", "module_2", "module_3"]
    A1 M12 -> ["module_10", "module_11"]

``Module.check_prerequisites`` (app/curriculum/models.py:105-113) keeps only
entries that are ``dict`` with ``type == 'module'``. Both lists reduce to empty,
the method returns ``(True, [])``, and since ``find_next_lesson_linear`` gates
exclusively through ``check_prerequisites``, these were silent no-ops: the whole
catalogue had zero working prerequisite checkpoints.

Changing the shape is not enough — the slugs are level-relative module *numbers*,
so each has to be resolved to a ``modules.id`` within the same level.

Data-only and idempotent: entries already in dict form are left untouched, and a
slug that resolves to nothing is kept verbatim rather than dropped, so no
authored intent is lost silently.

Revision ID: 20260808_normalize_module_prerequisites
Revises: 20260808_level_entry_prerequisites
Create Date: 2026-08-08
"""

import json
import re

import sqlalchemy as sa
from alembic import op

revision = '20260808_normalize_module_prerequisites'
down_revision = '20260808_level_entry_prerequisites'
branch_labels = None
depends_on = None

# Marks rows this migration rewrote, so downgrade restores exactly those.
_MARKER = 'slug_normalized'

MIN_SCORE = 70
MIN_PROGRESS = 80

_SLUG_RE = re.compile(r'^module[_\-\s]*(\d+)$', re.IGNORECASE)


def _load(raw):
    """`prerequisites` may arrive as JSON text or as an already-decoded list."""
    if raw is None:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def normalize_prerequisites(conn) -> int:
    """Rewrite slug prerequisites in place. Returns the number of modules changed."""
    changed_modules = 0

    rows = conn.execute(sa.text(
        'SELECT id, level_id, prerequisites FROM modules '
        'WHERE prerequisites IS NOT NULL'
    )).fetchall()

    for module_id, level_id, raw in rows:
        prereqs = _load(raw)
        if not isinstance(prereqs, list) or not prereqs:
            continue

        rewritten = []
        changed = False
        for entry in prereqs:
            match = _SLUG_RE.match(entry.strip()) if isinstance(entry, str) else None
            if match is None:
                rewritten.append(entry)
                continue

            target_id = conn.execute(
                sa.text(
                    'SELECT id FROM modules WHERE level_id = :lid AND number = :num'
                ),
                {'lid': level_id, 'num': int(match.group(1))},
            ).scalar()
            if target_id is None:
                # Unresolvable slug: keep it rather than delete an authored intent.
                rewritten.append(entry)
                continue

            rewritten.append({
                'type': 'module',
                'id': int(target_id),
                'min_score': MIN_SCORE,
                'min_progress': MIN_PROGRESS,
                'source': _MARKER,
                'legacy_slug': entry,
            })
            changed = True

        if changed:
            changed_modules += 1
            conn.execute(
                sa.text('UPDATE modules SET prerequisites = :p WHERE id = :id'),
                {'p': json.dumps(rewritten), 'id': module_id},
            )

    return changed_modules


def restore_slugs(conn) -> int:
    """Undo `normalize_prerequisites`. Returns the number of modules restored."""
    restored_modules = 0

    rows = conn.execute(sa.text(
        'SELECT id, prerequisites FROM modules '
        'WHERE prerequisites::text LIKE :marker'
    ), {'marker': f'%{_MARKER}%'}).fetchall()

    for module_id, raw in rows:
        prereqs = _load(raw)
        if not isinstance(prereqs, list):
            continue
        restored = [
            entry.get('legacy_slug')
            if isinstance(entry, dict) and entry.get('source') == _MARKER
            else entry
            for entry in prereqs
        ]
        restored_modules += 1
        conn.execute(
            sa.text('UPDATE modules SET prerequisites = :p WHERE id = :id'),
            {'p': json.dumps(restored), 'id': module_id},
        )

    return restored_modules


def upgrade():
    normalize_prerequisites(op.get_bind())


def downgrade():
    restore_slugs(op.get_bind())
