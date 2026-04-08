"""Add onboarding_completed field to users table

Revision ID: add_onboarding_fields
Revises:
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_onboarding_fields'
down_revision = None  # Will be set by alembic
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users',
                  sa.Column('onboarding_completed', sa.Boolean(),
                            nullable=False, server_default='false'))


def downgrade():
    op.drop_column('users', 'onboarding_completed')
