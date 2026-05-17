"""Add ipa_transcription column to collection_words.

Revision ID: 20260513_ipa_transcription
Revises: 20260513_word_collocations
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa


revision = '20260513_ipa_transcription'
down_revision = '20260513_word_collocations'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _column_exists(table: str, column: str) -> bool:
    inspector = sa.inspect(_bind())
    return any(c['name'] == column for c in inspector.get_columns(table))


def upgrade():
    if not _column_exists('collection_words', 'ipa_transcription'):
        op.add_column(
            'collection_words',
            sa.Column('ipa_transcription', sa.Text(), nullable=True),
        )


def downgrade():
    if _column_exists('collection_words', 'ipa_transcription'):
        op.drop_column('collection_words', 'ipa_transcription')
