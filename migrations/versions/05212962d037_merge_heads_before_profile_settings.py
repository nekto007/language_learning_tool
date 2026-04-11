"""merge_heads_before_profile_settings

Revision ID: 05212962d037
Revises: add_notifications_table, add_referral_system
Create Date: 2026-04-10 12:45:42.842296

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '05212962d037'
down_revision = ('add_notifications_table', 'add_referral_system')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
