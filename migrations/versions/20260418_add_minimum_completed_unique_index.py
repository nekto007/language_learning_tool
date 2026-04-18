"""Add unique partial index on daily_plan_events for minimum_completed events.

Prevents duplicate minimum_completed rows under concurrent requests.

Revision ID: 20260418_add_minimum_completed_unique_index
Revises: 20260418_add_daily_plan_events
Create Date: 2026-04-18
"""
from alembic import op


revision = '20260418_add_minimum_completed_unique_index'
down_revision = '20260418_add_daily_plan_events'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE UNIQUE INDEX uq_daily_plan_events_minimum_completed
        ON daily_plan_events (user_id, plan_date)
        WHERE event_type = 'minimum_completed'
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_daily_plan_events_minimum_completed')
