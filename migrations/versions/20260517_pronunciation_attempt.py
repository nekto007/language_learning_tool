"""Add pronunciation_attempts table.

Revision ID: 20260517_pronunciation_attempt
Revises: 20260516_plan_difficulty
Create Date: 2026-05-17
"""

from alembic import op
import sqlalchemy as sa

revision = '20260517_pronunciation_attempt'
down_revision = '20260516_plan_difficulty'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pronunciation_attempts',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer, sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('word', sa.String(200), nullable=False),
        sa.Column('recognized_text', sa.String(500), nullable=False, server_default=''),
        sa.Column('matched', sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        'idx_pronunciation_attempts_user_created',
        'pronunciation_attempts',
        ['user_id', 'created_at'],
    )
    op.create_index(
        'idx_pronunciation_attempts_word',
        'pronunciation_attempts',
        ['word'],
    )


def downgrade():
    op.drop_index('idx_pronunciation_attempts_word', table_name='pronunciation_attempts')
    op.drop_index('idx_pronunciation_attempts_user_created', table_name='pronunciation_attempts')
    op.drop_table('pronunciation_attempts')
