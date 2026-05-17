"""Add streak_shield_active to users.

Revision ID: 20260523_streak_shield
Revises: 20260523_lesson_feedback
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa

revision = '20260523_streak_shield'
down_revision = '20260523_lesson_feedback'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'streak_shield_active',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )


def downgrade():
    op.drop_column('users', 'streak_shield_active')
