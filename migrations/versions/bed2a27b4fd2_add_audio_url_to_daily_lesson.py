"""add audio_url to daily_lesson

Revision ID: bed2a27b4fd2
Revises: a1b2c3d4e5f6
Create Date: 2025-12-11 19:51:17.789882

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bed2a27b4fd2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def _table_exists(table_name):
    insp = sa.inspect(op.get_bind())
    return table_name in insp.get_table_names()


def _column_exists(table_name, column_name):
    insp = sa.inspect(op.get_bind())
    return any(column['name'] == column_name for column in insp.get_columns(table_name))


def _index_exists(table_name, index_name):
    insp = sa.inspect(op.get_bind())
    return any(index.get('name') == index_name for index in insp.get_indexes(table_name))


def upgrade():
    if not _table_exists('daily_lessons'):
        return

    # Add audio_url column to daily_lessons table
    if not _column_exists('daily_lessons', 'audio_url'):
        op.add_column('daily_lessons',
            sa.Column('audio_url', sa.Text(), nullable=True)
        )

    # Add index for faster queries on lessons with audio
    if not _index_exists('daily_lessons', 'idx_daily_lessons_audio_url'):
        op.create_index(
            'idx_daily_lessons_audio_url',
            'daily_lessons',
            ['audio_url'],
            unique=False,
            postgresql_where=sa.text('audio_url IS NOT NULL')
        )


def downgrade():
    if not _table_exists('daily_lessons'):
        return

    # Remove index first
    if _index_exists('daily_lessons', 'idx_daily_lessons_audio_url'):
        op.drop_index('idx_daily_lessons_audio_url', table_name='daily_lessons')

    # Remove column
    if _column_exists('daily_lessons', 'audio_url'):
        op.drop_column('daily_lessons', 'audio_url')
