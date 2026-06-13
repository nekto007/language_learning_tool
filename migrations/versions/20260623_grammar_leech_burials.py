"""Add consecutive_leech_burials to user_grammar_exercises (audit E-017).

Lets grammar SRS route through the shared apply_review_schedule helper so
leech burials escalate (7→14→21 days) like word cards instead of always 7.

Revision ID: 20260623_grammar_leech_burials
Revises: 20260622_reengagement_dedup
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa


revision = '20260623_grammar_leech_burials'
down_revision = '20260622_reengagement_dedup'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_grammar_exercises',
        sa.Column('consecutive_leech_burials', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade():
    op.drop_column('user_grammar_exercises', 'consecutive_leech_burials')
