"""Add total_books_completed and total_chapters_read to user_statistics.

Revision ID: 20260530_user_stats_books_completed
Revises: 20260607_word_contrasts
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa


revision = '20260530_user_stats_books_completed'
down_revision = '20260607_word_contrasts'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_statistics',
        sa.Column(
            'total_books_completed',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )
    op.add_column(
        'user_statistics',
        sa.Column(
            'total_chapters_read',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade():
    op.drop_column('user_statistics', 'total_chapters_read')
    op.drop_column('user_statistics', 'total_books_completed')
