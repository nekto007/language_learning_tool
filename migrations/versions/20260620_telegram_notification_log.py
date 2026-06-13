"""Add telegram_notification_log for idempotent scheduled notifications.

One row per (user_id, kind, sent_on local date). The UNIQUE constraint makes
the send-claim race-safe, so concurrent scheduler processes (multiple workers,
the scheduler container, or transient deploy overlap) cannot send the same
reminder twice.

Revision ID: 20260620_telegram_notification_log
Revises: 20260619_daily_plan_snapshot
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = '20260620_telegram_notification_log'
down_revision = '20260619_daily_plan_snapshot'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'telegram_notification_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('sent_on', sa.Date(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'kind', 'sent_on', name='uq_tg_notif_user_kind_date'),
    )
    op.create_index('idx_tg_notif_user_date', 'telegram_notification_log', ['user_id', 'sent_on'])


def downgrade():
    op.drop_index('idx_tg_notif_user_date', table_name='telegram_notification_log')
    op.drop_table('telegram_notification_log')
