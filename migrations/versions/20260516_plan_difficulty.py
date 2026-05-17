"""Add plan_difficulty to users table.

Revision ID: 20260516_plan_difficulty
Revises: 20260516_plan_pause
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa

revision = '20260516_plan_difficulty'
down_revision = '20260516_plan_pause'
branch_labels = None
depends_on = None

_VALID = ('light', 'normal', 'intensive')


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'plan_difficulty',
            sa.String(20),
            nullable=False,
            server_default='normal',
        ),
    )
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT ck_users_plan_difficulty "
        "CHECK (plan_difficulty IN ('light', 'normal', 'intensive'))"
    )


def downgrade():
    op.execute(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_plan_difficulty"
    )
    op.drop_column('users', 'plan_difficulty')
