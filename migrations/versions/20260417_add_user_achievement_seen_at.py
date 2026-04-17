"""Add seen_at column to user_achievements.

Supports the dashboard badge-popup feature: freshly awarded badges carry a
NULL seen_at until the user visits the dashboard, at which point the popup is
shown and seen_at is set so the popup does not reappear on later visits.

Revision ID: 20260417_add_ua_seen_at
Revises: 20260417_add_rank_fields
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa


revision = '20260417_add_ua_seen_at'
down_revision = '20260417_add_rank_fields'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_achievements', schema=None) as batch_op:
        batch_op.add_column(sa.Column('seen_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('user_achievements', schema=None) as batch_op:
        batch_op.drop_column('seen_at')
