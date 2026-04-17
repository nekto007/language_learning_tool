"""Add daily_plan_log table for day-secured state tracking.

One row per user per calendar day. Records the selected mission type
and when the day was secured (all required phases completed).

Revision ID: 20260418_add_daily_plan_log
Revises: 20260417_add_consecutive_perfect_days
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = '20260418_add_daily_plan_log'
down_revision = '20260417_add_consecutive_perfect_days'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'daily_plan_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('plan_date', sa.Date(), nullable=False),
        sa.Column('mission_type', sa.String(20), nullable=True),
        sa.Column('secured_at', sa.DateTime(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.UniqueConstraint(
            'user_id', 'plan_date', name='uq_daily_plan_log_user_date'
        ),
    )
    op.create_index(
        'idx_daily_plan_log_user_date',
        'daily_plan_log',
        ['user_id', 'plan_date'],
    )


def downgrade():
    op.drop_index('idx_daily_plan_log_user_date', table_name='daily_plan_log')
    op.drop_table('daily_plan_log')
