"""Create word_collocations table.

Revision ID: 20260513_word_collocations
Revises: 20260512_user_writing_attempt
Create Date: 2026-05-13
"""

from alembic import op
import sqlalchemy as sa


revision = '20260513_word_collocations'
down_revision = '20260512_user_writing_attempt'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _table_exists(table: str) -> bool:
    return table in sa.inspect(_bind()).get_table_names()


def upgrade():
    if _table_exists('word_collocations'):
        return
    op.create_table(
        'word_collocations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'word_id', sa.Integer(),
            sa.ForeignKey('collection_words.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('collocation_phrase', sa.Text(), nullable=False),
        sa.Column('translation', sa.Text(), nullable=False),
        sa.Column('example', sa.Text(), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
        ),
    )
    op.create_index(
        'idx_word_collocations_word_id',
        'word_collocations', ['word_id'],
    )


def downgrade():
    if _table_exists('word_collocations'):
        op.drop_index('idx_word_collocations_word_id', table_name='word_collocations')
        op.drop_table('word_collocations')
