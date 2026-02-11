"""Drop old telegram tables and create new ones for accountability bot.

Revision ID: recreate_telegram
Revises: add_grammar_status
"""
from alembic import op
import sqlalchemy as sa

revision = 'recreate_telegram'
down_revision = 'add_grammar_status'
branch_labels = None
depends_on = None


def upgrade():
    # Drop old telegram tables (order matters for FK constraints)
    op.execute('DROP TABLE IF EXISTS bot_daily_progress CASCADE')
    op.execute('DROP TABLE IF EXISTS telegram_link_codes CASCADE')
    op.execute('DROP TABLE IF EXISTS telegram_tokens CASCADE')
    op.execute('DROP TABLE IF EXISTS telegram_users CASCADE')

    # Create new tables
    op.create_table(
        'telegram_users_v2',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False, unique=True),
        sa.Column('username', sa.String(64)),
        sa.Column('timezone', sa.String(50), nullable=False, server_default='Europe/Moscow'),
        sa.Column('morning_reminder', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('evening_summary', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('skip_nudge', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('streak_alert', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('linked_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
    )
    op.create_index('idx_telegram_users_v2_telegram_id', 'telegram_users_v2', ['telegram_id'])
    op.create_index('idx_telegram_users_v2_user_id', 'telegram_users_v2', ['user_id'])

    op.create_table(
        'telegram_link_codes_v2',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('code', sa.String(6), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('telegram_link_codes_v2')
    op.drop_table('telegram_users_v2')
