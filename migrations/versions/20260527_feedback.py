"""Add feedback table for in-app product feedback channel.

Revision ID: 20260527_feedback
Revises: 20260524_lesson_skip
Create Date: 2026-05-27
"""

from alembic import op
import sqlalchemy as sa

revision = '20260527_feedback'
down_revision = '20260524_lesson_skip'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'feedback',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('category', sa.String(length=16), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('url', sa.String(length=2048), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='new'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_feedback_status_created', 'feedback', ['status', 'created_at'])
    op.create_index('idx_feedback_user_id', 'feedback', ['user_id'])


def downgrade():
    op.drop_index('idx_feedback_user_id', table_name='feedback')
    op.drop_index('idx_feedback_status_created', table_name='feedback')
    op.drop_table('feedback')
