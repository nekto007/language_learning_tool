"""Add admin_audit_log table for tracking destructive admin actions.

Revision ID: 20260416_add_admin_audit_log
Revises: f1e2d3c4b5a6
Create Date: 2026-04-16
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '20260416_add_admin_audit_log'
down_revision = 'f1e2d3c4b5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'admin_audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('admin_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(128), nullable=False),
        sa.Column('target_type', sa.String(64), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_admin_audit_log_admin_id', 'admin_audit_log', ['admin_id'])
    op.create_index('ix_admin_audit_log_created_at', 'admin_audit_log', ['created_at'])


def downgrade():
    op.drop_index('ix_admin_audit_log_created_at', 'admin_audit_log')
    op.drop_index('ix_admin_audit_log_admin_id', 'admin_audit_log')
    op.drop_table('admin_audit_log')
