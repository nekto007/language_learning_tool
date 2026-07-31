"""Persist best and last curriculum lesson scores separately.

Revision ID: 20260714_lesson_retry_scores
Revises: 20260626_drop_use_mission_plan
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa


revision = '20260714_lesson_retry_scores'
down_revision = '20260626_drop_use_mission_plan'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('lesson_progress', sa.Column('best_score', sa.Float(), nullable=True))
    op.add_column('lesson_progress', sa.Column('last_score', sa.Float(), nullable=True))
    op.execute(
        'UPDATE lesson_progress '
        'SET best_score = COALESCE(score, 0), '
        'last_score = score '
        'WHERE best_score IS NULL'
    )
    op.alter_column('lesson_progress', 'best_score', nullable=False, server_default='0')


def downgrade():
    op.drop_column('lesson_progress', 'last_score')
    op.drop_column('lesson_progress', 'best_score')
