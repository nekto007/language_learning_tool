"""Reset adaptive_tier_floor for all users.

Revision ID: 20260615_reset_adaptive_tier_floors
Revises: 20260614_consecutive_leech_burials
Create Date: 2026-06-15

Bug #2 fix follow-up: previously ``_resolve_tier`` treated a large overdue
pile as a tier-drop signal, which collapsed REVIEW% to 0 and trapped users
in a recovery death-spiral (no reviews allowed → backlog keeps growing).
After the fix backlog only throttles NEW; REVIEW always follows accuracy.

Existing floors stored under the old logic may still be ``collapse``/
``critical`` for users whose accuracy is fine — they'd be forced through
2–4 days of ladder recovery for no reason. Reset everyone to ``normal``;
future drops will be recorded under the new accuracy-only logic.

Idempotent: re-running just re-zeroes the columns.
"""

from alembic import op


revision = '20260615_reset_adaptive_tier_floors'
down_revision = '20260614_consecutive_leech_burials'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE user_statistics
        SET adaptive_tier_floor = 'normal',
            adaptive_tier_floor_date = NULL
        """
    )


def downgrade():
    # No-op: there's no way to reconstruct the original floors, and
    # leaving them at 'normal' is the safe state regardless.
    pass
