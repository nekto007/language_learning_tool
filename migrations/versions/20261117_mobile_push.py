"""Opt-in iOS push devices, reminder preferences and delivery claims."""
from alembic import op
import sqlalchemy as sa

revision = '20261117_mobile_push'
down_revision = '20261117_mobile_auth'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('native_push_preferences',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('hours', sa.JSON(), nullable=False))
    op.create_table('native_push_devices',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('secret_hash', sa.String(64), nullable=False),
        sa.Column('token', sa.String(512), nullable=False),
        sa.Column('environment', sa.String(16), nullable=False),
        sa.Column('auth_version', sa.String(64), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('token', 'environment', name='uq_native_push_token_environment'))
    op.create_index('ix_native_push_devices_user_id', 'native_push_devices', ['user_id'])
    op.create_table('native_push_deliveries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('study_date', sa.Date(), nullable=False),
        sa.Column('slot', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('accepted', sa.Integer(), nullable=False),
        sa.UniqueConstraint('user_id', 'study_date', 'slot', name='uq_native_push_user_day_slot'))
    op.create_index('ix_native_push_deliveries_created_at', 'native_push_deliveries', ['created_at'])


def downgrade():
    op.drop_table('native_push_deliveries')
    op.drop_table('native_push_devices')
    op.drop_table('native_push_preferences')
