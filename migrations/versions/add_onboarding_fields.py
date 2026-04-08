"""Add onboarding_completed field to users table

Revision ID: add_onboarding_fields
Revises:
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_onboarding_fields'
down_revision = 'add_streak_steps_fields'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users',
                  sa.Column('onboarding_completed', sa.Boolean(),
                            nullable=False, server_default='false'))
    # Mark existing users as already onboarded — only new users should see the wizard
    op.execute("UPDATE users SET onboarding_completed = true")


def downgrade():
    op.drop_column('users', 'onboarding_completed')
