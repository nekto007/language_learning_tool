"""Add plan_paused_until to users table.

Revision ID: 20260516_plan_pause
Revises: 20260515_word_etymology
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa

revision = '20260516_plan_pause'
down_revision = '20260515_word_etymology'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('plan_paused_until', sa.Date(), nullable=True),
    )


def downgrade():
    op.drop_column('users', 'plan_paused_until')
