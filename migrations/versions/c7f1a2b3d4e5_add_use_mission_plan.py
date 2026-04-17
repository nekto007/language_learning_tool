"""Add use_mission_plan feature flag to the users table.

Introduces the mission-based daily plan experience (Progress, Repair, Reading missions)
as an opt-in feature controlled per user. The flag defaults to false so all existing
users continue receiving the legacy v2 plan until explicitly migrated.

Routing logic in app/daily_plan/service.py reads this flag to call
get_daily_plan_unified() -> mission pipeline or fall back to get_daily_plan_v2().

Revision ID: c7f1a2b3d4e5
Revises: a5832ad173e0
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa

revision = 'c7f1a2b3d4e5'
down_revision = 'a5832ad173e0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('use_mission_plan', sa.Boolean(), server_default='false', nullable=False))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('use_mission_plan')
