"""Add lesson_skips table for defer-to-tomorrow skip quota.

Revision ID: 20260524_lesson_skip
Revises: 20260601_activity_feed_indexes
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa

revision = '20260524_lesson_skip'
down_revision = '20260601_activity_feed_indexes'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'lesson_skips' not in inspector.get_table_names():
        op.create_table(
            'lesson_skips',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('lesson_id', sa.Integer(), nullable=False),
            sa.Column('skipped_on_date', sa.Date(), nullable=False),
            sa.Column('defer_until_date', sa.Date(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'lesson_id', 'skipped_on_date', name='uq_lesson_skip_user_lesson_date'),
        )
        op.create_index('idx_lesson_skips_user_defer', 'lesson_skips', ['user_id', 'defer_until_date'])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'lesson_skips' in inspector.get_table_names():
        op.drop_index('idx_lesson_skips_user_defer', table_name='lesson_skips')
        op.drop_table('lesson_skips')
