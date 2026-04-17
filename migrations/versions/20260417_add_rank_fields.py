"""Add rank progression fields to user_statistics.

Adds plans_completed_total and current_rank columns to support the daily plan
rank/title system (Novice -> Explorer -> Student -> Expert -> Master -> Legend
-> Grandmaster). Rank is derived from plans_completed_total via
app.achievements.ranks.get_user_rank.

Revision ID: 20260417_add_rank_fields
Revises: 41c72a04754a
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = '20260417_add_rank_fields'
down_revision = '41c72a04754a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_statistics', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'plans_completed_total',
                sa.Integer(),
                nullable=False,
                server_default='0',
            )
        )
        batch_op.add_column(
            sa.Column(
                'current_rank',
                sa.String(length=32),
                nullable=False,
                server_default='novice',
            )
        )


def downgrade():
    with op.batch_alter_table('user_statistics', schema=None) as batch_op:
        batch_op.drop_column('current_rank')
        batch_op.drop_column('plans_completed_total')
