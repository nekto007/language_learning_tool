"""Publisher free access and optional short-reading metadata.

Revision ID: 20261122_a1_short_readings
Revises: 20261122_auth_mail_submission
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20261122_a1_short_readings'
down_revision = '20261122_auth_mail_submission'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('book', sa.Column('is_free_access', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('book', sa.Column('reading', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=True))


def downgrade():
    op.drop_column('book', 'reading')
    op.drop_column('book', 'is_free_access')
