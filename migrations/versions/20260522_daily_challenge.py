"""Add daily_challenges and daily_challenge_completions tables.

Revision ID: 20260522_daily_challenge
Revises: 20260521_study_minutes
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa

revision = '20260522_daily_challenge'
down_revision = '20260521_study_minutes'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'daily_challenges',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('challenge_date', sa.Date(), nullable=False),
        sa.Column('lesson_id', sa.Integer(), nullable=True),
        sa.Column('bonus_xp', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('category', sa.String(30), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('challenge_date', name='uq_daily_challenge_date'),
    )
    op.create_index('idx_daily_challenges_date', 'daily_challenges', ['challenge_date'])

    op.create_table(
        'daily_challenge_completions',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('time_spent_seconds', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['challenge_id'], ['daily_challenges.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('challenge_id', 'user_id', name='uq_challenge_completion_user'),
    )
    op.create_index('idx_challenge_completions_user', 'daily_challenge_completions', ['user_id'])
    op.create_index('idx_challenge_completions_challenge', 'daily_challenge_completions', ['challenge_id'])


def downgrade():
    op.drop_index('idx_challenge_completions_challenge', table_name='daily_challenge_completions')
    op.drop_index('idx_challenge_completions_user', table_name='daily_challenge_completions')
    op.drop_table('daily_challenge_completions')
    op.drop_index('idx_daily_challenges_date', table_name='daily_challenges')
    op.drop_table('daily_challenges')
