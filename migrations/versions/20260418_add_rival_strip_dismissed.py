"""Add rival_strip_dismissed column to users table.

Allows users to permanently dismiss the Phase 3 ghost rival strip.

Revision ID: 20260418_add_rival_strip_dismissed
Revises: 20260418_add_birth_year_to_users
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = '20260418_add_rival_strip_dismissed'
down_revision = '20260418_add_birth_year_to_users'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'rival_strip_dismissed',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade():
    op.drop_column('users', 'rival_strip_dismissed')
