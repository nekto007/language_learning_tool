"""Gate every level-entry module behind the previous level's last module.

Audit CNT-005 (cross-zone audit 2026-08-08). ``check_module_access`` makes the
first module of ANY level auto-accessible on purpose — a hard previous-level
check would break placement users. Its own comment names the safeguard that is
supposed to make that safe:

    "The safeguard against a B1 user jumping to C2's first module is that
     higher-level ENTRY modules must carry Module.prerequisites"

In the data that safeguard did not exist: only 2 of 86 modules carried any
prerequisites at all, both intra-level. So a learner 56% through A1 M2 was shown
A2 M1 in "Дальше по курсу", and from there walked the whole A2 spine on the
ordinary 80%-of-previous rule, never touching A1 M3-M16.

This writes, for each level after the first, a prerequisite pointing at the last
module of the preceding level, at the same 80% bar the intra-level rule uses.
Placement is unaffected: ``check_prerequisites(min_level_order=...)`` skips
prerequisites below the user's onboarding floor.

Data-only and idempotent — modules that already declare prerequisites are left
untouched, and downgrade removes only the rows this migration added.

Revision ID: 20260808_level_entry_prerequisites
Revises: 20260808_survey_prompts
Create Date: 2026-08-08
"""

import sqlalchemy as sa
from alembic import op

revision = '20260808_level_entry_prerequisites'
down_revision = '20260808_survey_prompts'
branch_labels = None
depends_on = None

# Marks the rows this migration owns, so downgrade cannot delete authored data.
_MARKER = 'level_entry_gate'

MIN_PROGRESS = 80
# Deliberately 0, and deliberately explicit. `check_prerequisites` defaults a
# missing `min_score` to PASSING_SCORE_PERCENT (70), and it compares that bar
# against `_get_module_completion`'s avg over LessonProgress.score for *every*
# completed lesson — including the types that complete without ever being
# graded (theory-only grammar lessons have their score stripped in
# routes/lessons.py and stay at the 0.0 column default). A learner who finished
# 100% of the module can therefore average below 70 and be locked out of the
# whole CEFR level for good. The gate we actually want is the 80% completion
# bar that the intra-level rule in check_module_access uses, which is exactly
# what MIN_PROGRESS expresses; the score bar has to be switched off explicitly.
MIN_SCORE = 0


def _level_entry_pairs(conn):
    """Yield (entry_module_id, previous_level_last_module_id) for every level.

    The prerequisite target must be a module the learner can actually finish:
    ``_get_module_completion`` reports 0% for a module with no lessons, so
    gating a level behind an empty trailing module would lock it for good — and
    ``find_next_lesson_linear`` reads that as "spine exhausted". Hence the
    target is the last module of the previous level that *has* lessons.
    """
    levels = conn.execute(sa.text(
        'SELECT id, "order" FROM cefr_levels ORDER BY "order"'
    )).fetchall()

    previous_last_module_id = None
    for level_id, _order in levels:
        modules = conn.execute(
            sa.text(
                'SELECT m.id FROM modules m WHERE m.level_id = :lid '
                'AND EXISTS (SELECT 1 FROM lessons l WHERE l.module_id = m.id) '
                'ORDER BY m.number'
            ),
            {'lid': level_id},
        ).fetchall()
        if not modules:
            continue

        entry_module_id = modules[0][0]
        if previous_last_module_id is not None:
            yield entry_module_id, previous_last_module_id
        previous_last_module_id = modules[-1][0]


def upgrade():
    import json

    conn = op.get_bind()

    for entry_id, prereq_id in _level_entry_pairs(conn):
        existing = conn.execute(
            sa.text('SELECT prerequisites FROM modules WHERE id = :id'),
            {'id': entry_id},
        ).scalar()

        if existing:
            continue  # authored prerequisites win

        payload = [{
            'type': 'module',
            'id': prereq_id,
            'min_score': MIN_SCORE,
            'min_progress': MIN_PROGRESS,
            'source': _MARKER,
        }]
        conn.execute(
            sa.text('UPDATE modules SET prerequisites = :p WHERE id = :id'),
            {'p': json.dumps(payload), 'id': entry_id},
        )


def strip_marker_entries(raw):
    """Drop only the entries this migration authored.

    Returns the surviving list (``None`` when nothing survives), or the sentinel
    ``False`` when the row must be left untouched — unparseable data, a
    non-list, or a marker that matched some other text in the column.
    """
    import json

    if isinstance(raw, (list, dict)):
        entries = raw
    else:
        try:
            entries = json.loads(raw)
        except (TypeError, ValueError):
            return False
    if not isinstance(entries, list):
        return False

    kept = [
        e for e in entries
        if not (isinstance(e, dict) and e.get('source') == _MARKER)
    ]
    if len(kept) == len(entries):
        return False
    return kept or None


def downgrade():
    """Remove only the entries this migration wrote.

    Nulling the whole column would also delete any prerequisite an admin
    appended to a level-entry module after the upgrade ran.
    """
    import json

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        'SELECT id, prerequisites FROM modules WHERE prerequisites::text LIKE :marker'
    ), {'marker': f'%{_MARKER}%'}).fetchall()

    for module_id, raw in rows:
        kept = strip_marker_entries(raw)
        if kept is False:
            continue
        conn.execute(
            sa.text('UPDATE modules SET prerequisites = :p WHERE id = :id'),
            {'p': json.dumps(kept) if kept else None, 'id': module_id},
        )
