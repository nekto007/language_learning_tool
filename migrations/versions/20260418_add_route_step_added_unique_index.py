"""Add unique partial index on daily_plan_events for route_step_added events.

Prevents duplicate route_step_added rows under concurrent requests,
ensuring add_route_steps_idempotent is truly idempotent under concurrency.

Revision ID: 20260418_add_route_step_added_unique_index
Revises: 20260418_add_minimum_completed_unique_index
Create Date: 2026-04-18
"""
from alembic import op


revision = '20260418_add_route_step_added_unique_index'
down_revision = '20260418_add_minimum_completed_unique_index'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE UNIQUE INDEX uq_daily_plan_events_route_step_added
        ON daily_plan_events (user_id, step_kind, plan_date)
        WHERE event_type = 'route_step_added'
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_daily_plan_events_route_step_added')
