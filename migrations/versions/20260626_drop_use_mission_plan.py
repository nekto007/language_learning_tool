"""Drop the vestigial use_mission_plan flag from users.

The mission plan was retired in the unified-plan refactor; no application
code reads this column (the telegram daily-plan path calls
``get_daily_plan_unified`` directly and the admin toggle route was removed).
It only lingered as a default nothing consumes.

Revision ID: 20260626_drop_use_mission_plan
Revises: 20260625_drop_use_plan_flags
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa

revision = '20260626_drop_use_mission_plan'
down_revision = '20260625_drop_use_plan_flags'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('users', 'use_mission_plan')


def downgrade():
    op.add_column(
        'users',
        sa.Column(
            'use_mission_plan',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )
