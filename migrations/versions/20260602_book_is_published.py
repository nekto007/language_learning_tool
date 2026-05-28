"""Add is_published to book table.

Revision ID: 20260602_book_is_published
Revises: 20260601_activity_feed_indexes
Create Date: 2026-06-02
"""

from alembic import op
import sqlalchemy as sa

revision = '20260602_book_is_published'
down_revision = '20260601_activity_feed_indexes'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'book',
        sa.Column(
            'is_published',
            sa.Boolean(),
            nullable=False,
            server_default='true',
        ),
    )


def downgrade():
    op.drop_column('book', 'is_published')
