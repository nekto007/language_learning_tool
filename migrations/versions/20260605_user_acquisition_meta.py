"""Add acquisition_meta JSONB to users for UTM attribution.

Revision ID: 20260605_user_acquisition_meta
Revises: 04cb4dfdc672
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '20260605_user_acquisition_meta'
down_revision = '04cb4dfdc672'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('acquisition_meta', JSONB(), nullable=True),
    )


def downgrade():
    op.drop_column('users', 'acquisition_meta')
