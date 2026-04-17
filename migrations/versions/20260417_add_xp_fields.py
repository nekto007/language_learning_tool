"""Add XP and level fields to user_statistics.

Adds total_xp and current_level columns to support the daily mission XP
progression system. XP is awarded on phase completion and drives level-up
notifications independently from the rank system.

Revision ID: 20260417_add_xp_fields
Revises: 20260417_add_rank_fields
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = '20260417_add_xp_fields'
down_revision = '20260417_daily_race'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_statistics', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'total_xp',
                sa.Integer(),
                nullable=False,
                server_default='0',
            )
        )
        batch_op.add_column(
            sa.Column(
                'current_level',
                sa.Integer(),
                nullable=False,
                server_default='1',
            )
        )


def downgrade():
    with op.batch_alter_table('user_statistics', schema=None) as batch_op:
        batch_op.drop_column('current_level')
        batch_op.drop_column('total_xp')
