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


def _table_exists(table_name):
    insp = sa.inspect(op.get_bind())
    return table_name in insp.get_table_names()


def _column_exists(table_name, column_name):
    insp = sa.inspect(op.get_bind())
    return any(col['name'] == column_name for col in insp.get_columns(table_name))


def upgrade():
    if not _table_exists('user_statistics'):
        return

    with op.batch_alter_table('user_statistics', schema=None) as batch_op:
        if not _column_exists('user_statistics', 'consecutive_perfect_days'):
            batch_op.add_column(
                sa.Column(
                    'consecutive_perfect_days',
                    sa.Integer(),
                    nullable=False,
                    server_default='0',
                )
            )


def downgrade():
    if not _table_exists('user_statistics'):
        return

    with op.batch_alter_table('user_statistics', schema=None) as batch_op:
        if _column_exists('user_statistics', 'consecutive_perfect_days'):
            batch_op.drop_column('consecutive_perfect_days')
