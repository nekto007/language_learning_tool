"""Add password_reset_tokens table for single-use token enforcement.

Previously, password reset tokens were stored as a plain column on the users table
with no expiry or usage tracking, allowing a leaked token to be replayed indefinitely.

This migration creates a dedicated password_reset_tokens table with:
- token_hash: SHA-256 hash of the reset token (never store raw tokens in DB)
- used_at: set to the timestamp when the token was consumed, preventing reuse
- CASCADE delete on user removal to avoid orphaned tokens

Revision ID: add_password_reset_tokens
Revises: f1e2d3c4b5a6
Create Date: 2026-04-16
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_password_reset_tokens'
down_revision = 'f1e2d3c4b5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('used_at', sa.DateTime(), nullable=True),
    )
    op.create_index('idx_prt_token_hash', 'password_reset_tokens', ['token_hash'])
    op.create_index('idx_prt_user_id', 'password_reset_tokens', ['user_id'])


def downgrade():
    op.drop_index('idx_prt_user_id', table_name='password_reset_tokens')
    op.drop_index('idx_prt_token_hash', table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
