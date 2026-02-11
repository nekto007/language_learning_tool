"""Add reflection fields to telegram_users_v2

Revision ID: add_telegram_reflection_fields
Revises: add_telegram_bot_tables
Create Date: 2026-02-11

Adds:
- last_reflection: user's self-assessment after evening summary
- last_reflection_at: timestamp of last reflection
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_telegram_reflection_fields'
down_revision = 'add_telegram_bot_tables'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('telegram_users_v2',
                  sa.Column('last_reflection', sa.String(10), nullable=True))
    op.add_column('telegram_users_v2',
                  sa.Column('last_reflection_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('telegram_users_v2', 'last_reflection_at')
    op.drop_column('telegram_users_v2', 'last_reflection')
