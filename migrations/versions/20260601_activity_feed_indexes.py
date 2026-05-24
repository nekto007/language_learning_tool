"""Add indexes for admin activity feed ordering and filtering.

Revision ID: 20260601_activity_feed_indexes
Revises: 20260525_add_site_settings
Create Date: 2026-06-01

Adds DESC-friendly btree indexes on the columns that the admin activity feed
orders/filters by. Without these, paginating the feed forces sequential scans
on streak_events / admin_audit_log / daily_plan_log.
"""

from alembic import op
import sqlalchemy as sa


revision = '20260601_activity_feed_indexes'
down_revision = '20260525_add_site_settings'
branch_labels = None
depends_on = None


def _has_index(inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return any(idx['name'] == name for idx in inspector.get_indexes(table))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_index(inspector, 'admin_audit_log', 'idx_admin_audit_log_created_at'):
        op.create_index(
            'idx_admin_audit_log_created_at',
            'admin_audit_log',
            ['created_at'],
            unique=False,
        )

    if not _has_index(inspector, 'streak_events', 'idx_streak_events_type_created'):
        op.create_index(
            'idx_streak_events_type_created',
            'streak_events',
            ['event_type', 'created_at'],
            unique=False,
        )

    if not _has_index(inspector, 'daily_plan_log', 'idx_daily_plan_log_secured_at'):
        op.create_index(
            'idx_daily_plan_log_secured_at',
            'daily_plan_log',
            ['secured_at'],
            unique=False,
            postgresql_where=sa.text('secured_at IS NOT NULL'),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, 'daily_plan_log', 'idx_daily_plan_log_secured_at'):
        op.drop_index('idx_daily_plan_log_secured_at', table_name='daily_plan_log')
    if _has_index(inspector, 'streak_events', 'idx_streak_events_type_created'):
        op.drop_index('idx_streak_events_type_created', table_name='streak_events')
    if _has_index(inspector, 'admin_audit_log', 'idx_admin_audit_log_created_at'):
        op.drop_index('idx_admin_audit_log_created_at', table_name='admin_audit_log')
