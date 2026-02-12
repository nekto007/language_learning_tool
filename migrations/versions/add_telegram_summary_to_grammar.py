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


def upgrade():
    op.add_column('grammar_topics', sa.Column('telegram_summary', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('grammar_topics', 'telegram_summary')
