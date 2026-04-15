"""Add reflection fields to telegram_users_v2

Revision ID: add_telegram_reflection_fields
Revises: add_telegram_notification_hours
Create Date: 2026-02-11

Adds:
- last_reflection: user's self-assessment after evening summary
- last_reflection_at: timestamp of last reflection
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_telegram_reflection_fields'
down_revision = 'add_telegram_notification_hours'
branch_labels = None
depends_on = None


def _table_exists(table):
    """Check if a table exists."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _column_exists(table, column):
    """Check if a column already exists in the table."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns(table)]
    return column in columns


def upgrade():
    if not _table_exists('telegram_users_v2'):
        return

    if not _column_exists('telegram_users_v2', 'last_reflection'):
        op.add_column('telegram_users_v2',
                      sa.Column('last_reflection', sa.String(10), nullable=True))
    if not _column_exists('telegram_users_v2', 'last_reflection_at'):
        op.add_column('telegram_users_v2',
                      sa.Column('last_reflection_at', sa.DateTime(), nullable=True))


def downgrade():
    if not _table_exists('telegram_users_v2'):
        return

    if _column_exists('telegram_users_v2', 'last_reflection_at'):
        op.drop_column('telegram_users_v2', 'last_reflection_at')
    if _column_exists('telegram_users_v2', 'last_reflection'):
        op.drop_column('telegram_users_v2', 'last_reflection')
