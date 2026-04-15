"""Merge all current Alembic heads into a single head.

Revision ID: f1e2d3c4b5a6
Revises: add_telegram_reflection_fields, add_telegram_summary_to_grammar,
    bed2a27b4fd2, c7f1a2b3d4e5, create_grammar_lab_tables,
    rename_skip_nudge_to_nudge_enabled
Create Date: 2026-04-15
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = 'f1e2d3c4b5a6'
down_revision = (
    'add_telegram_reflection_fields',
    'add_telegram_summary_to_grammar',
    'bed2a27b4fd2',
    'c7f1a2b3d4e5',
    'create_grammar_lab_tables',
    'rename_skip_nudge_to_nudge_enabled',
)
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
