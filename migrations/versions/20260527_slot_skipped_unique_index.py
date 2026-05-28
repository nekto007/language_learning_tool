"""Add unique partial index on daily_plan_events for slot_skipped events.

Prevents duplicate slot_skipped rows under concurrent requests.
One slot-skip per user per calendar day is enforced at the DB level.

Revision ID: 20260527_slot_skipped_unique_index
Revises: 20260601_activity_feed_indexes
Create Date: 2026-05-27
"""
from alembic import op


revision = '20260527_slot_skipped_unique_index'
down_revision = '20260601_activity_feed_indexes'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DELETE FROM daily_plan_events
        WHERE event_type = 'slot_skipped'
          AND id NOT IN (
            SELECT MIN(id) FROM daily_plan_events
            WHERE event_type = 'slot_skipped'
            GROUP BY user_id, plan_date
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_plan_events_slot_skipped
        ON daily_plan_events (user_id, plan_date)
        WHERE event_type = 'slot_skipped'
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_daily_plan_events_slot_skipped')
