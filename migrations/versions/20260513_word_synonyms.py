"""Add synonyms and antonyms JSON columns to collection_words.

Revision ID: 20260513_word_synonyms
Revises: 20260513_ipa_transcription
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa


revision = '20260513_word_synonyms'
down_revision = '20260513_ipa_transcription'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _column_exists(table: str, column: str) -> bool:
    inspector = sa.inspect(_bind())
    return any(c['name'] == column for c in inspector.get_columns(table))


def upgrade():
    if not _column_exists('collection_words', 'synonyms'):
        op.add_column(
            'collection_words',
            sa.Column('synonyms', sa.JSON(), nullable=True),
        )
    if not _column_exists('collection_words', 'antonyms'):
        op.add_column(
            'collection_words',
            sa.Column('antonyms', sa.JSON(), nullable=True),
        )


def downgrade():
    if _column_exists('collection_words', 'antonyms'):
        op.drop_column('collection_words', 'antonyms')
    if _column_exists('collection_words', 'synonyms'):
        op.drop_column('collection_words', 'synonyms')
