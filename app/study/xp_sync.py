"""One-time sync helper: UserXP.total_xp -> UserStatistics.total_xp.

Extracted from the Alembic data migration so the logic is testable against the
regular test database (which bootstraps schema via ``db.create_all`` instead of
running migrations). The migration ``20260424_sync_user_xp_to_stats`` runs the
same SQL via ``op.get_bind()``.

Idempotent via the ``user_xp.synced_to_stats`` sentinel column: once a row has
been folded into ``user_statistics.total_xp`` it is flagged and skipped on
subsequent runs.
"""
from __future__ import annotations

import sqlalchemy as sa


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


def sync_user_xp_to_statistics(bind) -> None:
    """Execute the legacy-XP sync against the given SQLAlchemy bind."""
    bind.execute(ENSURE_STATS_ROWS_SQL)
    bind.execute(ADD_LEGACY_TOTALS_SQL)
    bind.execute(MARK_SYNCED_SQL)
