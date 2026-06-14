"""Idempotency constraint for plan-completion markers.

`record_plan_completion` (sole writer of UserStatistics.plans_completed_total /
current_rank) does a check-then-insert of a `plan_completed` StreakEvent with no
DB-level guard. This branch newly wired it into TWO near-concurrent callers — the
dashboard render (app/words/routes.py) and the /api/daily-status XHR the
dashboard fires on load — so two requests could both read "no marker", both
increment plans_completed_total, and both insert a duplicate event, inflating the
plan count and triggering premature/duplicate rank-ups.

Add a partial unique index on (user_id, event_date) WHERE event_type =
'plan_completed' (mirroring the sibling xp_linear / xp_curriculum_lesson indexes
in 20260621). The helper wraps its insert in a savepoint + IntegrityError
recovery against this index.

Revision ID: 20260624_plan_completed_dedup
Revises: 20260623_grammar_leech_burials
Create Date: 2026-06-24
"""
from alembic import op


revision = '20260624_plan_completed_dedup'
down_revision = '20260623_grammar_leech_burials'
branch_labels = None
depends_on = None


def upgrade():
    # Collapse any pre-existing duplicates to the earliest row per (user, day).
    op.execute(
        """
        DELETE FROM streak_events
        WHERE event_type = 'plan_completed'
          AND id NOT IN (
            SELECT MIN(id) FROM streak_events
            WHERE event_type = 'plan_completed'
            GROUP BY user_id, event_date
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_streak_events_plan_completed
        ON streak_events (user_id, event_date)
        WHERE event_type = 'plan_completed'
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_streak_events_plan_completed')
