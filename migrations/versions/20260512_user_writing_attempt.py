"""Create user_writing_attempts table for writing_prompt submission tracking.

Revision ID: 20260512_user_writing_attempt
Revises: 20260511_listening_goal
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = '20260512_user_writing_attempt'
down_revision = '20260511_listening_goal'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _table_exists(table: str) -> bool:
    return table in sa.inspect(_bind()).get_table_names()


def upgrade():
    if _table_exists('user_writing_attempts'):
        return
    op.create_table(
        'user_writing_attempts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_id', sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'lesson_id', sa.Integer(),
            sa.ForeignKey('lessons.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('response_text', sa.Text(), nullable=False),
        sa.Column('word_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'checklist_completed', sa.Boolean(), nullable=False, server_default='false'
        ),
        sa.Column(
            'created_at', sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
        ),
    )
    op.create_index(
        'idx_writing_attempts_user_created',
        'user_writing_attempts', ['user_id', 'created_at'],
    )
    op.create_index(
        'idx_writing_attempts_user_lesson',
        'user_writing_attempts', ['user_id', 'lesson_id'],
    )


def downgrade():
    if _table_exists('user_writing_attempts'):
        op.drop_index('idx_writing_attempts_user_lesson', table_name='user_writing_attempts')
        op.drop_index('idx_writing_attempts_user_created', table_name='user_writing_attempts')
        op.drop_table('user_writing_attempts')
