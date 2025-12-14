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


def upgrade():
    # Add audio_url column to daily_lessons table
    op.add_column('daily_lessons',
        sa.Column('audio_url', sa.Text(), nullable=True)
    )

    # Add index for faster queries on lessons with audio
    op.create_index(
        'idx_daily_lessons_audio_url',
        'daily_lessons',
        ['audio_url'],
        unique=False,
        postgresql_where=sa.text('audio_url IS NOT NULL')
    )


def downgrade():
    # Remove index first
    op.drop_index('idx_daily_lessons_audio_url', table_name='daily_lessons')

    # Remove column
    op.drop_column('daily_lessons', 'audio_url')
