"""Create vocab_annotations table.

Revision ID: 20260514_vocab_annotation
Revises: 20260514_word_frequency_band
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa


revision = '20260514_vocab_annotation'
down_revision = '20260514_word_frequency_band'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _table_exists(table: str) -> bool:
    return table in sa.inspect(_bind()).get_table_names()


def upgrade():
    if _table_exists('vocab_annotations'):
        return
    op.create_table(
        'vocab_annotations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_id', sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'word_id', sa.Integer(),
            sa.ForeignKey('collection_words.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column(
            'added_at', sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
        ),
    )
    op.create_index(
        'idx_vocab_annotations_user_word',
        'vocab_annotations', ['user_id', 'word_id'],
        unique=True,
    )
    op.create_index(
        'idx_vocab_annotations_user_id',
        'vocab_annotations', ['user_id'],
    )


def downgrade():
    if _table_exists('vocab_annotations'):
        op.drop_index('idx_vocab_annotations_user_word', table_name='vocab_annotations')
        op.drop_index('idx_vocab_annotations_user_id', table_name='vocab_annotations')
        op.drop_table('vocab_annotations')
