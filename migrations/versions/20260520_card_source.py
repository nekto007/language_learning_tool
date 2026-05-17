"""Add source column to user_card_directions.

Revision ID: 20260520_card_source
Revises: 20260519_custom_word_list
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa

revision = '20260520_card_source'
down_revision = '20260519_custom_word_list'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_card_directions',
        sa.Column('source', sa.String(50), nullable=True),
    )


def downgrade():
    op.drop_column('user_card_directions', 'source')
