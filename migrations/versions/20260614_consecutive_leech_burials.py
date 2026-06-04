"""Add consecutive_leech_burials counter to user_card_directions.

Revision ID: 20260614_consecutive_leech_burials
Revises: 20260613_adaptive_tier
Create Date: 2026-06-14

Раздел 9 of docs/srs-fix-plan.md: instead of a fixed 7-day bury on every
leech lapse, scale ``bury_days = LEECH_SUSPEND_DAYS * (1 + n)`` where
``n`` is the number of consecutive burials without an intervening
successful review. Counter resets to 0 on graduation from RELEARNING
back to REVIEW.
"""

from alembic import op
import sqlalchemy as sa


revision = '20260614_consecutive_leech_burials'
down_revision = '20260613_adaptive_tier'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_card_directions',
        sa.Column(
            'consecutive_leech_burials',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade():
    op.drop_column('user_card_directions', 'consecutive_leech_burials')
