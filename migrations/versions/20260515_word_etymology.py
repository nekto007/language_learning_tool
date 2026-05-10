"""Add etymology column to collection_words.

Revision ID: 20260515_word_etymology
Revises: 20260514_vocab_annotation
Create Date: 2026-05-15
"""

from alembic import op
import sqlalchemy as sa


revision = '20260515_word_etymology'
down_revision = '20260514_vocab_annotation'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _column_exists(table: str, column: str) -> bool:
    insp = sa.inspect(_bind())
    return any(c['name'] == column for c in insp.get_columns(table))


def upgrade():
    if not _column_exists('collection_words', 'etymology'):
        op.add_column(
            'collection_words',
            sa.Column('etymology', sa.Text(), nullable=True),
        )


def downgrade():
    if _column_exists('collection_words', 'etymology'):
        op.drop_column('collection_words', 'etymology')
