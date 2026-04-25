"""Drop legacy user_xp table.

The unified XP write-path now lives in ``app.achievements.xp_service.award_xp``
and writes only to ``user_statistics.total_xp``. The historical totals from the
legacy ``user_xp`` table were merged into ``user_statistics`` by migration
``20260424_sync_user_xp_to_stats``. With ``app/study/xp_service.py`` and the
``UserXP`` model removed, the table is now safe to drop.

Revision ID: 20260425_drop_user_xp
Revises: 20260425_grammar_cascade
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = '20260425_drop_user_xp'
down_revision = '20260425_grammar_cascade'
branch_labels = None
depends_on = None


def upgrade():
    # Use IF EXISTS / CASCADE for safety: the test bootstrap may not have created
    # the table, and we want the FK on user_id (ondelete=CASCADE) to drop cleanly.
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute('DROP TABLE IF EXISTS user_xp CASCADE')
    else:
        # SQLite (used in tests) — best-effort drop, no CASCADE keyword needed.
        op.execute('DROP TABLE IF EXISTS user_xp')


def downgrade():
    # Best-effort recreation. Data is lost — the legacy totals were already
    # merged into user_statistics.total_xp by 20260424_sync_user_xp_to_stats.
    op.create_table(
        'user_xp',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('total_xp', sa.Integer(), nullable=False, server_default='0'),
        sa.Column(
            'synced_to_stats',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id'),
    )
