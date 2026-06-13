"""Per-(user, day, campaign) dedup for re-engagement emails (audit E-087).

The day-3/7/30 re-engagement job now runs hourly (so every timezone's
delivery window is reached — E-088) and claims a streak_events marker before
sending. This partial-unique index makes the claim race-safe across processes:
a given user gets at most one of each campaign per local day.

Revision ID: 20260622_reengagement_dedup
Revises: 20260621_idempotency_constraints
Create Date: 2026-06-22
"""
from alembic import op


revision = '20260622_reengagement_dedup'
down_revision = '20260621_idempotency_constraints'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_streak_events_reengagement
        ON streak_events (user_id, event_date, (details->>'campaign'))
        WHERE event_type = 'reengagement_email'
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_streak_events_reengagement')
