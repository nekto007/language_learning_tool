"""Add anonymous landing cohorts and the transactional welcome email outbox.

Revision ID: 20261115_landing_signup_flow
Revises: 20260906_reading_goal_for_readers
"""
from alembic import op
import sqlalchemy as sa


revision = '20261115_landing_signup_flow'
down_revision = '20260906_reading_goal_for_readers'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'landing_visits',
        sa.Column('id', sa.String(43), primary_key=True),
        sa.Column('preview_id', sa.String(32), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime()),
        sa.Column('answered_at', sa.DateTime()),
        sa.Column('registration_clicked_at', sa.DateTime()),
        sa.Column('registration_opened_at', sa.DateTime()),
        sa.Column('registered_at', sa.DateTime()),
        sa.Column('first_correct', sa.Boolean()),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('source', sa.String(200)),
        sa.Column('medium', sa.String(200)),
        sa.Column('campaign', sa.String(200)),
    )
    op.create_index('ix_landing_visits_created_at', 'landing_visits', ['created_at'])
    op.create_index('ix_landing_visits_user_id', 'landing_visits', ['user_id'])
    op.create_table(
        'welcome_email_queue',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('available_at', sa.DateTime(), nullable=False),
        sa.Column('locked_at', sa.DateTime()),
        sa.Column('sent_at', sa.DateTime()),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_welcome_email_queue_due', 'welcome_email_queue', ['status', 'available_at'])


def downgrade():
    op.drop_index('ix_welcome_email_queue_due', table_name='welcome_email_queue')
    op.drop_table('welcome_email_queue')
    op.drop_index('ix_landing_visits_user_id', table_name='landing_visits')
    op.drop_index('ix_landing_visits_created_at', table_name='landing_visits')
    op.drop_table('landing_visits')
