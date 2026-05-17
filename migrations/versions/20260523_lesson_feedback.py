"""Add lesson_feedback table.

Revision ID: 20260523_lesson_feedback
Revises: 20260522_cultural_note
Create Date: 2026-05-23
"""

from alembic import op
import sqlalchemy as sa

revision = '20260523_lesson_feedback'
down_revision = '20260522_cultural_note'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lesson_feedback',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('lesson_id', sa.Integer(), nullable=False),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['lesson_id'], ['lessons.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_lesson_feedback_user_lesson', 'lesson_feedback', ['user_id', 'lesson_id'], unique=True)
    op.create_index('idx_lesson_feedback_lesson_id', 'lesson_feedback', ['lesson_id'])


def downgrade():
    op.drop_index('idx_lesson_feedback_lesson_id', table_name='lesson_feedback')
    op.drop_index('idx_lesson_feedback_user_lesson', table_name='lesson_feedback')
    op.drop_table('lesson_feedback')
