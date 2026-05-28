"""merge_heads_task46

Revision ID: 04cb4dfdc672
Revises: 20260527_feedback, 20260527_slot_skipped_unique_index, 20260602_book_is_published
Create Date: 2026-05-27 14:57:17.753326

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '04cb4dfdc672'
down_revision = ('20260527_feedback', '20260527_slot_skipped_unique_index', '20260602_book_is_published')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
