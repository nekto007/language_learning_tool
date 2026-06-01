"""merge_heads_feedback_chat

Revision ID: 034c1b5b2aaa
Revises: 20260530_user_stats_total_cards_reviewed, 20260603_feedback_chat
Create Date: 2026-06-01 17:52:11.604513

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '034c1b5b2aaa'
down_revision = ('20260530_user_stats_total_cards_reviewed', '20260603_feedback_chat')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
