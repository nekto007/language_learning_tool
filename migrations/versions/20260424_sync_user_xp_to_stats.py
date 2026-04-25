"""Sync UserXP.total_xp into UserStatistics.total_xp (one-time data migration).

Unifies the two parallel XP counters (``user_xp.total_xp`` written by the legacy
``study/xp_service.py`` and ``user_statistics.total_xp`` written by the modern
``achievements/xp_service.py``). Adds a sentinel column ``user_xp.synced_to_stats``
so the migration is idempotent and reruns are safe.

For each ``user_xp`` row with ``synced_to_stats = FALSE``:
  - ensure a ``user_statistics`` row exists for the user
  - add ``user_xp.total_xp`` to ``user_statistics.total_xp``
  - flip the sentinel

Revision ID: 20260424_sync_user_xp_to_stats
Revises: 20260420_linear_mass_enable
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa


revision = '20260424_sync_user_xp_to_stats'
down_revision = '20260420_linear_mass_enable'
branch_labels = None
depends_on = None


# Inlined from former app.study.xp_sync (deleted along with the legacy UserXP model).
ENSURE_STATS_ROWS_SQL = sa.text("""
    INSERT INTO user_statistics (user_id, total_xp, current_level)
    SELECT ux.user_id, 0, 1
    FROM user_xp ux
    WHERE ux.synced_to_stats = FALSE
      AND NOT EXISTS (
          SELECT 1 FROM user_statistics us WHERE us.user_id = ux.user_id
      )
""")

ADD_LEGACY_TOTALS_SQL = sa.text("""
    UPDATE user_statistics us
    SET total_xp = us.total_xp + ux.total_xp,
        updated_at = NOW()
    FROM user_xp ux
    WHERE us.user_id = ux.user_id
      AND ux.synced_to_stats = FALSE
      AND ux.total_xp > 0
""")

MARK_SYNCED_SQL = sa.text("""
    UPDATE user_xp
    SET synced_to_stats = TRUE
    WHERE synced_to_stats = FALSE
""")


def _sync_user_xp_to_statistics(bind) -> None:
    """Execute the legacy-XP sync against the given SQLAlchemy bind."""
    bind.execute(ENSURE_STATS_ROWS_SQL)
    bind.execute(ADD_LEGACY_TOTALS_SQL)
    bind.execute(MARK_SYNCED_SQL)


def upgrade():
    bind = op.get_bind()

    op.add_column(
        'user_xp',
        sa.Column(
            'synced_to_stats',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    _sync_user_xp_to_statistics(bind)


def downgrade():
    # Data merge cannot be safely undone (we cannot tell the legacy contribution
    # apart from subsequent mission/linear XP awards). Only drop the sentinel.
    op.drop_column('user_xp', 'synced_to_stats')
