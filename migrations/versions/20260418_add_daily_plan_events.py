"""Add daily_plan_events table for Phase 1-3 behavioral event tracking.

One row per event emitted during the infinite learning loop flow.
Used to measure H1 continuation rate: next_step_accepted / minimum_completed.

Revision ID: 20260418_add_daily_plan_events
Revises: 20260418_add_rival_strip_dismissed
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = '20260418_add_daily_plan_events'
down_revision = '20260418_add_rival_strip_dismissed'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'daily_plan_events',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('plan_date', sa.Date(), nullable=True),
        sa.Column('mission_type', sa.String(20), nullable=True),
        sa.Column('step_kind', sa.String(40), nullable=True),
        sa.Column('reason_text', sa.String(500), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )
    op.create_index(
        'idx_daily_plan_events_user_date',
        'daily_plan_events',
        ['user_id', 'plan_date'],
    )
    op.create_index(
        'idx_daily_plan_events_type',
        'daily_plan_events',
        ['event_type'],
    )


def downgrade():
    op.drop_index('idx_daily_plan_events_type', table_name='daily_plan_events')
    op.drop_index('idx_daily_plan_events_user_date', table_name='daily_plan_events')
    op.drop_table('daily_plan_events')
