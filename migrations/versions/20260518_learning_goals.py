"""Add daily_word_goal and weekly_lesson_goal to users.

Revision ID: 20260518_learning_goals
Revises: 20260517_pronunciation_attempt
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa

revision = '20260518_learning_goals'
down_revision = '20260517_pronunciation_attempt'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('daily_word_goal', sa.Integer(), nullable=False, server_default='10'),
    )
    op.add_column(
        'users',
        sa.Column('weekly_lesson_goal', sa.Integer(), nullable=False, server_default='5'),
    )


def downgrade():
    op.drop_column('users', 'weekly_lesson_goal')
    op.drop_column('users', 'daily_word_goal')
