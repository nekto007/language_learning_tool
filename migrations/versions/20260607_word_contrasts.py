"""Word contrast pairs.

Revision ID: 20260607_word_contrasts
Revises: 20260606_telegram_channel_posts
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = '20260607_word_contrasts'
down_revision = '20260606_telegram_channel_posts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'word_contrasts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'word_a_id', sa.Integer(),
            sa.ForeignKey('collection_words.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'word_b_id', sa.Integer(),
            sa.ForeignKey('collection_words.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('note_ru', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('word_a_id', 'word_b_id', name='uq_word_contrast_pair'),
    )
    op.create_index('idx_word_contrasts_word_a', 'word_contrasts', ['word_a_id'])
    op.create_index('idx_word_contrasts_word_b', 'word_contrasts', ['word_b_id'])


def downgrade():
    op.drop_index('idx_word_contrasts_word_b', table_name='word_contrasts')
    op.drop_index('idx_word_contrasts_word_a', table_name='word_contrasts')
    op.drop_table('word_contrasts')
