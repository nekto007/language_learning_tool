"""Add frequency_band SMALLINT to collection_words.

Revision ID: 20260514_word_frequency_band
Revises: 20260513_word_synonyms
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa


revision = '20260514_word_frequency_band'
down_revision = '20260513_word_synonyms'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _column_exists(table: str, column: str) -> bool:
    inspector = sa.inspect(_bind())
    return any(c['name'] == column for c in inspector.get_columns(table))


def upgrade():
    if not _column_exists('collection_words', 'frequency_band'):
        op.add_column(
            'collection_words',
            sa.Column('frequency_band', sa.SmallInteger(), nullable=True),
        )


def downgrade():
    if _column_exists('collection_words', 'frequency_band'):
        op.drop_column('collection_words', 'frequency_band')
