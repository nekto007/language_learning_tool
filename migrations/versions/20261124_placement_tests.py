"""Private placement banks, durable attempts and deferred level choice."""
from alembic import op
import sqlalchemy as sa

revision = '20261124_placement_tests'
down_revision = '20261122_a1_short_readings'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('placement_pending_level', sa.String(4), nullable=True))
    op.add_column('users', sa.Column('placement_pending_on', sa.Date(), nullable=True))
    op.create_table('placement_banks',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('label', sa.String(120), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.create_table('placement_attempts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bank_id', sa.String(64), sa.ForeignKey('placement_banks.id'), nullable=False),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('applied_at', sa.DateTime(), nullable=True))
    op.create_index('ix_placement_attempts_user_id', 'placement_attempts', ['user_id'])
    op.create_index('uq_placement_attempt_active_user', 'placement_attempts', ['user_id'], unique=True,
                    postgresql_where=sa.text("status = 'active'"), sqlite_where=sa.text("status = 'active'"))


def downgrade() -> None:
    op.drop_table('placement_attempts')
    op.drop_table('placement_banks')
    op.drop_column('users', 'placement_pending_on')
    op.drop_column('users', 'placement_pending_level')
