"""add telegram notification hour columns

Revision ID: add_telegram_notification_hours
Revises: 03a5a0454960
Create Date: 2026-02-21 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_telegram_notification_hours'
down_revision = '03a5a0454960'
branch_labels = None
depends_on = None


def _column_exists(table, column):
    """Check if a column already exists in the table."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns(table)]
    return column in columns


def _table_exists(table):
    """Check if a table exists."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade():
    if not _table_exists('telegram_users_v2'):
        return

    columns = {
        'morning_hour': '9',
        'nudge_hour': '14',
        'evening_hour': '21',
        'streak_hour': '22',
    }
    for col_name, default in columns.items():
        if not _column_exists('telegram_users_v2', col_name):
            op.add_column(
                'telegram_users_v2',
                sa.Column(col_name, sa.SmallInteger(), nullable=False, server_default=default),
            )


def downgrade():
    if not _table_exists('telegram_users_v2'):
        return

    for col_name in ('streak_hour', 'evening_hour', 'nudge_hour', 'morning_hour'):
        if _column_exists('telegram_users_v2', col_name):
            op.drop_column('telegram_users_v2', col_name)
