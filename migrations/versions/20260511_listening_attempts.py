"""Create listening_attempts table for dictation/audio_fill_blank submission tracking.

Revision ID: 20260511_listening_attempts
Revises: 20260426_reading_session
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = '20260511_listening_attempts'
down_revision = '20260426_reading_session'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _table_exists(table: str) -> bool:
    return table in sa.inspect(_bind()).get_table_names()


def upgrade():
    if _table_exists('listening_attempts'):
        return
    op.create_table(
        'listening_attempts',
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
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('replay_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'created_at', sa.DateTime(),
            nullable=False,
            server_default=sa.text('NOW()'),
        ),
    )
    op.create_index(
        'idx_listening_attempts_user_created',
        'listening_attempts', ['user_id', 'created_at'],
    )
    op.create_index(
        'idx_listening_attempts_lesson',
        'listening_attempts', ['lesson_id'],
    )


def downgrade():
    if not _table_exists('listening_attempts'):
        return
    op.drop_index('idx_listening_attempts_lesson', table_name='listening_attempts')
    op.drop_index('idx_listening_attempts_user_created', table_name='listening_attempts')
    op.drop_table('listening_attempts')
