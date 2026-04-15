"""Add telegram_summary to grammar_topics

Revision ID: add_telegram_summary_to_grammar
Revises:
Create Date: 2026-02-12

Adds telegram_summary text field for mini-summaries in morning reminders.
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_telegram_summary_to_grammar'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _column_exists(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns(table)]
    return column in columns


def upgrade():
    if not _table_exists('grammar_topics'):
        return
    if not _column_exists('grammar_topics', 'telegram_summary'):
        op.add_column('grammar_topics', sa.Column('telegram_summary', sa.Text(), nullable=True))


def downgrade():
    if not _table_exists('grammar_topics'):
        return
    if _column_exists('grammar_topics', 'telegram_summary'):
        op.drop_column('grammar_topics', 'telegram_summary')
