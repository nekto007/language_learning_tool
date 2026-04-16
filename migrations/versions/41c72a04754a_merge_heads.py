"""merge_heads

Revision ID: 41c72a04754a
Revises: 20260416_add_admin_audit_log, 20260416_add_composite_indexes
Create Date: 2026-04-16 23:32:49.980349

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '41c72a04754a'
down_revision = ('20260416_add_admin_audit_log', '20260416_add_composite_indexes')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
