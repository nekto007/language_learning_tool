"""Drop the learner-authored association cue from card directions.

Revision ID: 20260826_drop_personal_association
Revises: 20260815_seed_word_sets
Create Date: 2026-08-26
"""

from alembic import op
import sqlalchemy as sa


revision = '20260826_drop_personal_association'
down_revision = '20260815_seed_word_sets'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('user_card_directions', 'personal_association')


def downgrade():
    # Restores the column only; the notes themselves are not recoverable.
    op.add_column(
        'user_card_directions',
        sa.Column('personal_association', sa.Text(), nullable=True),
    )
