"""Add consecutive_perfect_days to user_statistics.

Tracks how many consecutive days the user completed all required mission
phases. Used to award escalating perfect-day XP multipliers.

Revision ID: 20260417_add_consecutive_perfect_days
Revises: 20260417_add_xp_fields
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = '20260417_add_consecutive_perfect_days'
down_revision = '20260417_add_xp_fields'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_statistics', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'consecutive_perfect_days',
                sa.Integer(),
                nullable=False,
                server_default='0',
            )
        )


def downgrade():
    with op.batch_alter_table('user_statistics', schema=None) as batch_op:
        batch_op.drop_column('consecutive_perfect_days')
