"""Add total_cards_reviewed to user_statistics.

Revision ID: 20260530_user_stats_total_cards_reviewed
Revises: 20260530_user_stats_books_completed
Create Date: 2026-05-30
"""

from alembic import op
import sqlalchemy as sa


revision = '20260530_user_stats_total_cards_reviewed'
down_revision = '20260530_user_stats_books_completed'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_statistics',
        sa.Column(
            'total_cards_reviewed',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )


def downgrade():
    op.drop_column('user_statistics', 'total_cards_reviewed')
