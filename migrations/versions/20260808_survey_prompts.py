"""Add per-user state for the two-week product survey prompt.

Answers are stored as ordinary feedback rows (category 'survey'); this table
only remembers whether a learner has already answered or asked to be left
alone, so the prompt can be shown at most twice per account.

Revision ID: 20260808_survey_prompts
Revises: 20260801_srs_exclusions_and_associations
Create Date: 2026-08-08
"""

from alembic import op
import sqlalchemy as sa


revision = '20260808_survey_prompts'
down_revision = '20260801_srs_exclusions_and_associations'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'survey_prompts',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('dismiss_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('dismissed_at', sa.DateTime(), nullable=True),
        sa.Column('answered_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade():
    op.drop_table('survey_prompts')
