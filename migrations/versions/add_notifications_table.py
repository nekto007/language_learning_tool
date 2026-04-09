"""Add notifications table

Revision ID: add_notifications_table
Revises: add_referral_fields
Create Date: 2026-04-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_notifications_table'
down_revision = 'add_referral_fields'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('link', sa.String(500), nullable=True),
        sa.Column('icon', sa.String(10), server_default='🔔'),
        sa.Column('read', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_notifications_user_read', 'notifications', ['user_id', 'read'])
    op.create_index('idx_notifications_user_created', 'notifications', ['user_id', 'created_at'])


def downgrade():
    op.drop_index('idx_notifications_user_created', table_name='notifications')
    op.drop_index('idx_notifications_user_read', table_name='notifications')
    op.drop_table('notifications')
