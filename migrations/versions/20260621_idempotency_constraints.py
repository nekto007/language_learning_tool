"""Idempotency constraints for XP and reminder dedup (audit E-001, E-002, E-079).

- Partial unique indexes on streak_events so concurrent linear-slot /
  curriculum-lesson XP awards can't double-insert (check-then-insert had no
  DB-level guard, unlike book/referral/game XP). The award helpers now wrap
  the insert in a savepoint + IntegrityError recovery against these indexes.
- reminder_logs.sent_on (DATE) + unique (user_id, sent_on) so two concurrent
  /admin/reminders/send requests can't both pass the 24h cooldown and double
  email a user.

Revision ID: 20260621_idempotency_constraints
Revises: 20260620_telegram_notification_log
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa


revision = '20260621_idempotency_constraints'
down_revision = '20260620_telegram_notification_log'
branch_labels = None
depends_on = None


def upgrade():
    # --- streak_events: linear-slot XP dedup (user, date, source) ---
    op.execute(
        """
        DELETE FROM streak_events
        WHERE event_type = 'xp_linear'
          AND id NOT IN (
            SELECT MIN(id) FROM streak_events
            WHERE event_type = 'xp_linear'
            GROUP BY user_id, event_date, (details->>'source')
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_streak_events_xp_linear_source
        ON streak_events (user_id, event_date, (details->>'source'))
        WHERE event_type = 'xp_linear'
        """
    )

    # --- streak_events: curriculum-lesson XP dedup (user, date, lesson_id) ---
    op.execute(
        """
        DELETE FROM streak_events
        WHERE event_type = 'xp_curriculum_lesson'
          AND id NOT IN (
            SELECT MIN(id) FROM streak_events
            WHERE event_type = 'xp_curriculum_lesson'
            GROUP BY user_id, event_date, (details->>'lesson_id')
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_streak_events_xp_curriculum_lesson
        ON streak_events (user_id, event_date, (details->>'lesson_id'))
        WHERE event_type = 'xp_curriculum_lesson'
        """
    )

    # --- reminder_logs: per-(user, day) dedup ---
    op.add_column('reminder_logs', sa.Column('sent_on', sa.Date(), nullable=True))
    op.execute("UPDATE reminder_logs SET sent_on = (sent_at)::date WHERE sent_on IS NULL")
    op.execute(
        """
        DELETE FROM reminder_logs
        WHERE sent_on IS NOT NULL
          AND id NOT IN (
            SELECT MIN(id) FROM reminder_logs
            WHERE sent_on IS NOT NULL
            GROUP BY user_id, sent_on
          )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_reminder_logs_user_sent_on
        ON reminder_logs (user_id, sent_on)
        WHERE sent_on IS NOT NULL
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_reminder_logs_user_sent_on')
    op.drop_column('reminder_logs', 'sent_on')
    op.execute('DROP INDEX IF EXISTS uq_streak_events_xp_curriculum_lesson')
    op.execute('DROP INDEX IF EXISTS uq_streak_events_xp_linear_source')
