"""Feedback triage fields.

Revision ID: 20260608_feedback_triage
Revises: 034c1b5b2aaa
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa


revision = '20260608_feedback_triage'
down_revision = '034c1b5b2aaa'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'feedback',
        sa.Column('priority', sa.String(length=16), nullable=False, server_default='normal'),
    )
    op.add_column('feedback', sa.Column('assignee_admin_id', sa.Integer(), nullable=True))
    op.add_column('feedback', sa.Column('reopened_at', sa.DateTime(), nullable=True))
    op.create_foreign_key(
        'fk_feedback_assignee_admin_id_users',
        'feedback',
        'users',
        ['assignee_admin_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index('idx_feedback_priority_status', 'feedback', ['priority', 'status'])
    op.create_index('idx_feedback_assignee_status', 'feedback', ['assignee_admin_id', 'status'])


def downgrade():
    op.drop_index('idx_feedback_assignee_status', table_name='feedback')
    op.drop_index('idx_feedback_priority_status', table_name='feedback')
    op.drop_constraint('fk_feedback_assignee_admin_id_users', 'feedback', type_='foreignkey')
    op.drop_column('feedback', 'reopened_at')
    op.drop_column('feedback', 'assignee_admin_id')
    op.drop_column('feedback', 'priority')
