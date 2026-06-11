"""Add profile_is_public privacy flag to users.

Revision ID: 20260616_profile_is_public
Revises: 20260615_reset_adaptive_tier_floors
Create Date: 2026-06-16

Public pages /u/<username> and /streak/<username> were visible for any
active user without consent. The flag keeps them public by default
(opt-out) but lets the user hide them; hidden pages stay visible to the
owner and admins only.
"""

from alembic import op
import sqlalchemy as sa


revision = '20260616_profile_is_public'
down_revision = '20260615_reset_adaptive_tier_floors'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'profile_is_public',
            sa.Boolean(),
            nullable=False,
            server_default='true',
        ),
    )


def downgrade():
    op.drop_column('users', 'profile_is_public')
