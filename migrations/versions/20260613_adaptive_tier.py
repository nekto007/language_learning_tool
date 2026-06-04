"""Add adaptive SRS tier fields to user_statistics.

Revision ID: 20260613_adaptive_tier
Revises: 20260611_reminder_tracking
Create Date: 2026-06-13

Adds `adaptive_tier_floor` (string, default 'normal') and
`adaptive_tier_floor_date` (date, nullable) to ``user_statistics``.

Used by ``SRSService.get_adaptive_limits`` to implement the day-ladder
recovery from ``collapse``/``critical``/``low`` back up to ``normal``: a
drop is immediate, recovery climbs +1 tier per day starting day 2 after
the drop (day 1 is a rest day). See ``docs/srs-fix-plan.md`` Раздел 5.
"""

from alembic import op
import sqlalchemy as sa


revision = '20260613_adaptive_tier'
down_revision = '20260611_reminder_tracking'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_statistics',
        sa.Column(
            'adaptive_tier_floor',
            sa.String(16),
            nullable=False,
            server_default='normal',
        ),
    )
    op.add_column(
        'user_statistics',
        sa.Column('adaptive_tier_floor_date', sa.Date(), nullable=True),
    )


def downgrade():
    op.drop_column('user_statistics', 'adaptive_tier_floor_date')
    op.drop_column('user_statistics', 'adaptive_tier_floor')
