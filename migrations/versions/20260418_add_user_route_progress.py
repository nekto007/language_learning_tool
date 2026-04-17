"""Add user_route_progress table for route step accumulation.

One row per user tracking total weighted steps, checkpoint number,
and steps within the current checkpoint stretch.

Revision ID: 20260418_add_user_route_progress
Revises: 20260418_add_daily_plan_log
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = '20260418_add_user_route_progress'
down_revision = '20260418_add_daily_plan_log'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_route_progress',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('total_steps', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('checkpoint_number', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('steps_in_checkpoint', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'last_updated',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.UniqueConstraint('user_id', name='uq_user_route_progress_user'),
    )
    op.create_index(
        'idx_user_route_progress_user',
        'user_route_progress',
        ['user_id'],
    )


def downgrade():
    op.drop_index('idx_user_route_progress_user', table_name='user_route_progress')
    op.drop_table('user_route_progress')
