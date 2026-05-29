"""Telegram channel posts queue.

Revision ID: 20260606_telegram_channel_posts
Revises: 20260605_user_acquisition_meta
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = '20260606_telegram_channel_posts'
down_revision = '20260605_user_acquisition_meta'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'telegram_channel_posts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('content_ref_type', sa.String(length=32), nullable=True),
        sa.Column('content_ref_id', sa.Integer(), nullable=True),
        sa.Column('scheduled_for', sa.DateTime(), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('message_id', sa.BigInteger(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='queued'),
        sa.Column('text_snapshot', sa.Text(), nullable=False, server_default=''),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('is_manual', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index(
        'idx_channel_posts_status_due',
        'telegram_channel_posts',
        ['status', 'scheduled_for'],
    )
    op.create_index(
        'idx_channel_posts_kind_ref',
        'telegram_channel_posts',
        ['kind', 'content_ref_type', 'content_ref_id'],
    )


def downgrade():
    op.drop_index('idx_channel_posts_kind_ref', table_name='telegram_channel_posts')
    op.drop_index('idx_channel_posts_status_due', table_name='telegram_channel_posts')
    op.drop_table('telegram_channel_posts')
