"""Add listening_goal_minutes to users table.

Revision ID: 20260511_listening_goal
Revises: 20260511_listening_attempts
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = '20260511_listening_goal'
down_revision = '20260511_listening_attempts'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _column_exists(table: str, column: str) -> bool:
    cols = [c['name'] for c in sa.inspect(_bind()).get_columns(table)]
    return column in cols


def upgrade():
    if not _column_exists('users', 'listening_goal_minutes'):
        op.add_column(
            'users',
            sa.Column(
                'listening_goal_minutes',
                sa.Integer(),
                nullable=True,
                server_default='10',
            ),
        )


def downgrade():
    if _column_exists('users', 'listening_goal_minutes'):
        op.drop_column('users', 'listening_goal_minutes')
