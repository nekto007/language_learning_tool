"""Add referral system (referral_code on users, referral_logs table)

Revision ID: add_referral_system
Revises: add_onboarding_fields
Create Date: 2026-04-08

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_referral_system'
down_revision = 'add_onboarding_fields'
branch_labels = None
depends_on = None


def upgrade():
    # Create referral_logs table
    op.create_table(
        'referral_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('referrer_id', sa.Integer(), nullable=False),
        sa.Column('referred_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['referrer_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['referred_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('referred_id'),
    )
    op.create_index('idx_referral_referrer', 'referral_logs', ['referrer_id'])

    # Add referral_code to users
    op.add_column('users', sa.Column('referral_code', sa.String(16), nullable=True))
    op.create_unique_constraint('uq_users_referral_code', 'users', ['referral_code'])

    # Generate referral codes for existing users
    import uuid
    conn = op.get_bind()
    users = conn.execute(sa.text('SELECT id FROM users WHERE referral_code IS NULL'))
    for row in users:
        code = uuid.uuid4().hex[:8]
        conn.execute(
            sa.text('UPDATE users SET referral_code = :code WHERE id = :id'),
            {'code': code, 'id': row[0]}
        )


def downgrade():
    op.drop_constraint('uq_users_referral_code', 'users', type_='unique')
    op.drop_column('users', 'referral_code')
    op.drop_index('idx_referral_referrer', table_name='referral_logs')
    op.drop_table('referral_logs')
