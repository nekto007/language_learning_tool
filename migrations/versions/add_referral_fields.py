"""Add user acquisition fields: onboarding, referral, unsubscribe

Revision ID: add_referral_fields
Revises: add_streak_steps_fields
Create Date: 2026-04-09
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_referral_fields'
down_revision = 'add_streak_steps_fields'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # Helper: add column only if it doesn't exist
    def add_col_safe(table, col, col_type):
        result = conn.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ), {'t': table, 'c': col})
        if not result.fetchone():
            op.add_column(table, sa.Column(col, col_type))

    # Onboarding
    add_col_safe('users', 'onboarding_completed', sa.Boolean())
    add_col_safe('users', 'onboarding_level', sa.String(4))
    add_col_safe('users', 'onboarding_focus', sa.String(100))

    # Referral system
    add_col_safe('users', 'referral_code', sa.String(16))
    add_col_safe('users', 'referred_by_id', sa.Integer())

    # Create index/FK only if not exists
    try:
        op.create_index('ix_users_referral_code', 'users', ['referral_code'], unique=True)
    except Exception:
        pass
    try:
        op.create_foreign_key(
            'fk_users_referred_by_id', 'users', 'users',
            ['referred_by_id'], ['id'], ondelete='SET NULL'
        )
    except Exception:
        pass

    # Email unsubscribe
    add_col_safe('users', 'email_unsubscribe_token', sa.String(64))
    add_col_safe('users', 'email_opted_out', sa.Boolean())
    try:
        op.create_index('ix_users_email_unsubscribe_token', 'users', ['email_unsubscribe_token'], unique=True)
    except Exception:
        pass


def downgrade():
    op.drop_column('users', 'email_opted_out')
    op.drop_index('ix_users_email_unsubscribe_token', table_name='users')
    op.drop_column('users', 'email_unsubscribe_token')
    op.drop_constraint('fk_users_referred_by_id', 'users', type_='foreignkey')
    op.drop_index('ix_users_referral_code', table_name='users')
    op.drop_column('users', 'referred_by_id')
    op.drop_column('users', 'referral_code')
    op.drop_column('users', 'onboarding_focus')
    op.drop_column('users', 'onboarding_level')
    op.drop_column('users', 'onboarding_completed')
