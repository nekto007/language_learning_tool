"""Create user_reading_sessions for the reading-slot time gate.

The linear plan reading slot used to credit completion on any 5%
``UserChapterProgress.offset_pct`` delta — easily farmed by scrolling.
This table records actual time-on-page so the slot's XP path can require
both ``offset_delta >= 0.05`` and ``time_spent >= 60s``.

Revision ID: 20260426_reading_session
Revises: 20260425_grammar_cascade
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = '20260426_reading_session'
down_revision = '20260425_grammar_cascade'
branch_labels = None
depends_on = None


def _bind():
    return op.get_bind()


def _table_exists(table: str) -> bool:
    insp = sa.inspect(_bind())
    return table in insp.get_table_names()


def upgrade():
    if _table_exists('user_reading_sessions'):
        return
    op.create_table(
        'user_reading_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_id', sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'chapter_id', sa.Integer(),
            sa.ForeignKey('chapter.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('offset_delta', sa.Float(), nullable=False, server_default='0'),
    )
    op.create_index(
        'idx_user_reading_session_user_chapter',
        'user_reading_sessions', ['user_id', 'chapter_id'],
    )
    op.create_index(
        'idx_user_reading_session_started',
        'user_reading_sessions', ['started_at'],
    )


def downgrade():
    if not _table_exists('user_reading_sessions'):
        return
    op.drop_index('idx_user_reading_session_started', table_name='user_reading_sessions')
    op.drop_index('idx_user_reading_session_user_chapter', table_name='user_reading_sessions')
    op.drop_table('user_reading_sessions')
