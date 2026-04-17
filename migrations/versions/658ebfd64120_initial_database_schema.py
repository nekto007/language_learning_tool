"""Initial database schema

Revision ID: 658ebfd64120
Revises: 
Create Date: 2025-11-20 01:36:05.790900

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '658ebfd64120'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(table_name):
    insp = sa.inspect(op.get_bind())
    return table_name in insp.get_table_names()


def _index_exists(table_name, index_name):
    insp = sa.inspect(op.get_bind())
    return any(index.get('name') == index_name for index in insp.get_indexes(table_name))


def upgrade():
    if not _table_exists('telegram_tokens'):
        return

    with op.batch_alter_table('telegram_tokens', schema=None) as batch_op:
        for index_name in (
            batch_op.f('idx_telegram_tokens_expires_at'),
            batch_op.f('idx_telegram_tokens_revoked'),
            batch_op.f('idx_telegram_tokens_token'),
            batch_op.f('idx_telegram_tokens_user_id'),
        ):
            if _index_exists('telegram_tokens', index_name):
                batch_op.drop_index(index_name)


def downgrade():
    if not _table_exists('telegram_tokens'):
        return

    with op.batch_alter_table('telegram_tokens', schema=None) as batch_op:
        index_specs = (
            (batch_op.f('idx_telegram_tokens_user_id'), ['user_id']),
            (batch_op.f('idx_telegram_tokens_token'), ['token']),
            (batch_op.f('idx_telegram_tokens_revoked'), ['revoked']),
            (batch_op.f('idx_telegram_tokens_expires_at'), ['expires_at']),
        )
        for index_name, columns in index_specs:
            if not _index_exists('telegram_tokens', index_name):
                batch_op.create_index(index_name, columns, unique=False)
