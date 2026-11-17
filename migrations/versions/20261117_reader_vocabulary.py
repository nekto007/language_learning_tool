"""Private reader words, contexts and idempotent sync receipts.
Revision ID: 20261117_reader_vocabulary
Revises: 20261116_native_learning_runs
"""
from alembic import op
import sqlalchemy as sa
revision = '20261117_reader_vocabulary'
down_revision = '20261116_native_learning_runs'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('native_reader_vocabulary',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table('native_reader_vocabulary')
