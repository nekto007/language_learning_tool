"""Add extended metrics to UserLessonProgress

Revision ID: d35366cf95ab
Revises: 51563928c8a8
Create Date: 2025-11-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'd35366cf95ab'
down_revision = '51563928c8a8'
branch_labels = None
depends_on = None


def upgrade():
    """Add extended metrics columns for analytics and adaptive learning"""
    # Add errors_count column
    op.add_column('user_lesson_progress',
        sa.Column('errors_count', sa.Integer(), nullable=True, default=0)
    )

    # Add error_types JSONB column for tracking error categories
    op.add_column('user_lesson_progress',
        sa.Column('error_types', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )

    # Add last_attempt_at timestamp
    op.add_column('user_lesson_progress',
        sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True)
    )

    # Add review_intervals JSONB column for spaced repetition tracking
    op.add_column('user_lesson_progress',
        sa.Column('review_intervals', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade():
    """Remove extended metrics columns"""
    op.drop_column('user_lesson_progress', 'review_intervals')
    op.drop_column('user_lesson_progress', 'last_attempt_at')
    op.drop_column('user_lesson_progress', 'error_types')
    op.drop_column('user_lesson_progress', 'errors_count')
