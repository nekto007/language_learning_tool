"""Ensure ON DELETE CASCADE on grammar_exercises FKs.

The model definitions for ``user_grammar_exercises.exercise_id`` and
``grammar_attempts.exercise_id`` already declare ``ondelete='CASCADE'`` but
historic deployments either pre-date that declaration or were created before
the ``user_grammar_exercises`` table even had a migration. Without DB-level
cascade, deleting a ``grammar_exercises`` row leaves orphaned attempts/SRS
rows. This migration is idempotent — it inspects the current FK definition
and only rewrites it when ``ON DELETE`` is not ``CASCADE``. SQLite is skipped
because Alembic batch ALTER on FKs is fragile and tests use SQLite.

Revision ID: 20260425_grammar_cascade
Revises: 20260424_sync_user_xp_to_stats
Create Date: 2026-04-25
"""

from alembic import op
import sqlalchemy as sa


revision = '20260425_grammar_cascade'
down_revision = '20260424_sync_user_xp_to_stats'
branch_labels = None
depends_on = None


_TARGETS = (
    # (table, local_column, referent_table, referent_column)
    ('user_grammar_exercises', 'exercise_id', 'grammar_exercises', 'id'),
    ('grammar_attempts', 'exercise_id', 'grammar_exercises', 'id'),
)


def _bind():
    return op.get_bind()


def _is_postgres() -> bool:
    return _bind().dialect.name == 'postgresql'


def _table_exists(table: str) -> bool:
    insp = sa.inspect(_bind())
    return table in insp.get_table_names()


def _find_fk(table: str, column: str, referent: str):
    insp = sa.inspect(_bind())
    for fk in insp.get_foreign_keys(table):
        cols = fk.get('constrained_columns') or []
        if cols == [column] and fk.get('referred_table') == referent:
            return fk
    return None


def _ensure_cascade(table: str, column: str, referent: str, referent_column: str) -> None:
    if not _table_exists(table):
        return
    fk = _find_fk(table, column, referent)
    options = (fk or {}).get('options') or {}
    if fk and (options.get('ondelete') or '').upper() == 'CASCADE':
        return

    if fk and fk.get('name'):
        op.drop_constraint(fk['name'], table, type_='foreignkey')

    new_name = f'fk_{table}_{column}_cascade'
    op.create_foreign_key(
        new_name,
        table,
        referent,
        [column],
        [referent_column],
        ondelete='CASCADE',
    )


def upgrade():
    if not _is_postgres():
        # SQLite (test sandbox) cannot ALTER FKs without table rebuild and
        # already inherits CASCADE from the SQLAlchemy model on db.create_all().
        return
    for target in _TARGETS:
        _ensure_cascade(*target)


def downgrade():
    # Removing CASCADE would re-introduce orphan risk; intentional no-op.
    pass
