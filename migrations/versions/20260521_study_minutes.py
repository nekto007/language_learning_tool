"""Add daily_study_minutes table.

Revision ID: 20260521_study_minutes
Revises: 20260520_card_source
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa

revision = '20260521_study_minutes'
down_revision = '20260520_card_source'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'daily_study_minutes',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('study_date', sa.Date(), nullable=False),
        sa.Column('minutes', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_daily_study_minutes_user_date',
        'daily_study_minutes',
        ['user_id', 'study_date'],
        unique=True,
    )


def downgrade():
    op.drop_index('idx_daily_study_minutes_user_date', table_name='daily_study_minutes')
    op.drop_table('daily_study_minutes')
