"""Persist one resumable native SRS run per account.
Revision ID: 20261116_native_srs_state
Revises: 20261115_landing_signup_flow
"""
from alembic import op
import sqlalchemy as sa
revision = '20261116_native_srs_state'
down_revision = '20261115_landing_signup_flow'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('native_srs_state',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('study_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('study_day', sa.String(10), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False))

def downgrade():
    op.drop_table('native_srs_state')
