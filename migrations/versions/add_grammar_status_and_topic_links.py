"""Add grammar topic status field and grammar_topic_id FK to lessons

Revision ID: add_grammar_status
Revises:
Create Date: 2026-02-10
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_grammar_status'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add status column to user_grammar_topic_status
    op.add_column(
        'user_grammar_topic_status',
        sa.Column('status', sa.String(20), nullable=False, server_default='new')
    )

    # Backfill: set 'theory_completed' where theory_completed = True
    op.execute("""
        UPDATE user_grammar_topic_status
        SET status = 'theory_completed'
        WHERE theory_completed = TRUE
    """)

    # 2. Add grammar_topic_id column to lessons
    op.add_column(
        'lessons',
        sa.Column('grammar_topic_id', sa.Integer(), nullable=True)
    )

    # Add FK constraint
    op.create_foreign_key(
        'fk_lessons_grammar_topic_id',
        'lessons', 'grammar_topics',
        ['grammar_topic_id'], ['id'],
        ondelete='SET NULL'
    )

    # Add index
    op.create_index(
        'idx_lessons_grammar_topic_id',
        'lessons',
        ['grammar_topic_id']
    )


def downgrade():
    op.drop_index('idx_lessons_grammar_topic_id', table_name='lessons')
    op.drop_constraint('fk_lessons_grammar_topic_id', 'lessons', type_='foreignkey')
    op.drop_column('lessons', 'grammar_topic_id')
    op.drop_column('user_grammar_topic_status', 'status')
