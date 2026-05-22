"""Add use_unified_plan feature flag to users.

Revision ID: 20260524_use_unified_plan
Revises: 20260523_streak_shield
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = '20260524_use_unified_plan'
down_revision = '20260523_streak_shield'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'use_unified_plan',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade():
    op.drop_column('users', 'use_unified_plan')
