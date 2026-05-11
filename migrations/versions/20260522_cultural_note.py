"""Add cultural_notes table.

Revision ID: 20260522_cultural_note
Revises: 20260522_daily_challenge
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa

revision = '20260522_cultural_note'
down_revision = '20260522_daily_challenge'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cultural_notes',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('word_id', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('context', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['word_id'], ['collection_words.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_cultural_notes_word_id', 'cultural_notes', ['word_id'])


def downgrade():
    op.drop_index('idx_cultural_notes_word_id', table_name='cultural_notes')
    op.drop_table('cultural_notes')
