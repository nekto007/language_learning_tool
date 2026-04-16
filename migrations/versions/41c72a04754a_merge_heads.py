"""Merge diverged Alembic heads into a single head.

Two migration branches diverged during the backend improvement sprint:
- 20260416_add_admin_audit_log: admin_audit_log table for tracking destructive actions
- 20260416_add_composite_indexes: performance indexes on study_sessions, quiz_results, lesson_attempts

This merge migration reunites both branches so alembic heads reports a single head
and CI alembic check passes.

Revision ID: 41c72a04754a
Revises: 20260416_add_admin_audit_log, 20260416_add_composite_indexes
Create Date: 2026-04-16 23:32:49.980349

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '41c72a04754a'
down_revision = ('20260416_add_admin_audit_log', '20260416_add_composite_indexes')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
