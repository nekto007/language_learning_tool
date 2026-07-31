"""Add personal SRS exclusions and direction-specific associations.

Revision ID: 20260801_srs_exclusions_and_associations
Revises: 20260731_card_recovery_state
Create Date: 2026-08-01
"""

from alembic import op
import sqlalchemy as sa


revision = '20260801_srs_exclusions_and_associations'
down_revision = '20260731_card_recovery_state'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_words',
        sa.Column('srs_excluded', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.add_column('user_words', sa.Column('srs_excluded_at', sa.DateTime(), nullable=True))
    op.add_column('user_card_directions', sa.Column('personal_association', sa.Text(), nullable=True))
    op.create_index('idx_user_words_srs_excluded', 'user_words', ['user_id', 'srs_excluded'])


def downgrade():
    op.drop_index('idx_user_words_srs_excluded', table_name='user_words')
    op.drop_column('user_card_directions', 'personal_association')
    op.drop_column('user_words', 'srs_excluded_at')
    op.drop_column('user_words', 'srs_excluded')
