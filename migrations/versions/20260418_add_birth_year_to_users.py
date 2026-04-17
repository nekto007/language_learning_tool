"""Add birth_year column to users table for adult age-gating.

Used by the Phase 3 ghost rival strip to gate rivalry features to adults only.
Null means unknown age (treated as adult for backward compat).

Revision ID: 20260418_add_birth_year_to_users
Revises: 20260418_add_user_route_progress
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa


revision = '20260418_add_birth_year_to_users'
down_revision = '20260418_add_user_route_progress'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('birth_year', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('users', 'birth_year')
