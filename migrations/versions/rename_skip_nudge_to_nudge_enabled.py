"""Rename skip_nudge to nudge_enabled in telegram_users_v2

Revision ID: rename_skip_nudge_to_nudge_enabled
Revises:
Create Date: 2026-02-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'rename_skip_nudge_to_nudge_enabled'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _column_exists(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns(table)]
    return column in columns


def upgrade():
    if not _table_exists('telegram_users_v2'):
        return
    if _column_exists('telegram_users_v2', 'skip_nudge') and not _column_exists('telegram_users_v2', 'nudge_enabled'):
        op.alter_column('telegram_users_v2', 'skip_nudge', new_column_name='nudge_enabled')


def downgrade():
    if not _table_exists('telegram_users_v2'):
        return
    if _column_exists('telegram_users_v2', 'nudge_enabled') and not _column_exists('telegram_users_v2', 'skip_nudge'):
        op.alter_column('telegram_users_v2', 'nudge_enabled', new_column_name='skip_nudge')
