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


def _table_exists(table_name):
    insp = sa.inspect(op.get_bind())
    return table_name in insp.get_table_names()


def _column_exists(table_name, column_name):
    insp = sa.inspect(op.get_bind())
    return any(col['name'] == column_name for col in insp.get_columns(table_name))


def upgrade():
    """Add extended metrics columns for analytics and adaptive learning"""
    if not _table_exists('user_lesson_progress'):
        return

    # Add errors_count column
    if not _column_exists('user_lesson_progress', 'errors_count'):
        op.add_column('user_lesson_progress',
            sa.Column('errors_count', sa.Integer(), nullable=True, default=0)
        )

    # Add error_types JSONB column for tracking error categories
    if not _column_exists('user_lesson_progress', 'error_types'):
        op.add_column('user_lesson_progress',
            sa.Column('error_types', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )

    # Add last_attempt_at timestamp
    if not _column_exists('user_lesson_progress', 'last_attempt_at'):
        op.add_column('user_lesson_progress',
            sa.Column('last_attempt_at', sa.DateTime(timezone=True), nullable=True)
        )

    # Add review_intervals JSONB column for spaced repetition tracking
    if not _column_exists('user_lesson_progress', 'review_intervals'):
        op.add_column('user_lesson_progress',
            sa.Column('review_intervals', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )


def downgrade():
    """Remove extended metrics columns"""
    if not _table_exists('user_lesson_progress'):
        return

    if _column_exists('user_lesson_progress', 'review_intervals'):
        op.drop_column('user_lesson_progress', 'review_intervals')
    if _column_exists('user_lesson_progress', 'last_attempt_at'):
        op.drop_column('user_lesson_progress', 'last_attempt_at')
    if _column_exists('user_lesson_progress', 'error_types'):
        op.drop_column('user_lesson_progress', 'error_types')
    if _column_exists('user_lesson_progress', 'errors_count'):
        op.drop_column('user_lesson_progress', 'errors_count')
