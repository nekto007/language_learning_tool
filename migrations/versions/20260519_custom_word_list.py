"""Add custom_word_lists and custom_word_list_entries tables.

Revision ID: 20260519_custom_word_list
Revises: 20260518_learning_goals
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa

revision = '20260519_custom_word_list'
down_revision = '20260518_learning_goals'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'custom_word_lists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_custom_word_list_user_id', 'custom_word_lists', ['user_id'])

    op.create_table(
        'custom_word_list_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('list_id', sa.Integer(), nullable=False),
        sa.Column('word', sa.Text(), nullable=False),
        sa.Column('translation', sa.Text(), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['list_id'], ['custom_word_lists.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('list_id', 'word', name='uix_custom_list_word'),
    )
    op.create_index('idx_custom_word_list_entry_list_id', 'custom_word_list_entries', ['list_id'])


def downgrade():
    op.drop_index('idx_custom_word_list_entry_list_id', table_name='custom_word_list_entries')
    op.drop_table('custom_word_list_entries')
    op.drop_index('idx_custom_word_list_user_id', table_name='custom_word_lists')
    op.drop_table('custom_word_lists')
