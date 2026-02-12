"""Rename skip_nudge to nudge_enabled in telegram_users_v2

Revision ID: rename_skip_nudge_to_nudge_enabled
Revises:
Create Date: 2026-02-12
"""
from alembic import op


revision = 'rename_skip_nudge_to_nudge_enabled'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('telegram_users_v2', 'skip_nudge',
                    new_column_name='nudge_enabled')


def downgrade():
    op.alter_column('telegram_users_v2', 'nudge_enabled',
                    new_column_name='skip_nudge')
