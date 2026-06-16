"""Drop vestigial use_linear_plan / use_unified_plan flags from users.

Both columns are dead: every plan path is now the unified static snapshot,
no application code branches on either flag (the dashboard route renders the
unified dashboard unconditionally, and the linear/mission gates were removed).
The columns only lingered as defaults nothing reads.

Revision ID: 20260625_drop_use_plan_flags
Revises: 20260624_plan_completed_dedup
Create Date: 2026-06-25
"""

from alembic import op
import sqlalchemy as sa

revision = '20260625_drop_use_plan_flags'
down_revision = '20260624_plan_completed_dedup'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('users', 'use_linear_plan')
    op.drop_column('users', 'use_unified_plan')


def downgrade():
    op.add_column(
        'users',
        sa.Column(
            'use_unified_plan',
            sa.Boolean(),
            nullable=False,
            server_default='true',
        ),
    )
    op.add_column(
        'users',
        sa.Column(
            'use_linear_plan',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )
