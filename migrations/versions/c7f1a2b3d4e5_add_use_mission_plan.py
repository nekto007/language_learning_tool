"""add use_mission_plan flag to users

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
