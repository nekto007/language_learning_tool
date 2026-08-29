"""Unique partial index on streak_events for the perfect-day bonus.

One xp_perfect_day row per user per local day, enforced at the DB level.
award_perfect_day_xp_idempotent used a bare check-then-insert; the
day-secured sweepers added in DP-035 make concurrent calls routine, so the
insert needs a real arbiter (DP-051).

Revision ID: 20260829_perfect_day_unique_index
Revises: 20260828_study_session_word_set
Create Date: 2026-08-29
"""
from alembic import op


revision = '20260829_perfect_day_unique_index'
down_revision = '20260828_study_session_word_set'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DELETE FROM streak_events
        WHERE event_type = 'xp_perfect_day'
          AND id NOT IN (
            SELECT MIN(id) FROM streak_events
            WHERE event_type = 'xp_perfect_day'
            GROUP BY user_id, event_date
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_streak_events_perfect_day
        ON streak_events (user_id, event_date)
        WHERE event_type = 'xp_perfect_day'
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_streak_events_perfect_day')
