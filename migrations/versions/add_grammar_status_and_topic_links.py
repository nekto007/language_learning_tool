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


def _table_exists(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _column_exists(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = [c['name'] for c in insp.get_columns(table)]
    return column in columns


def _foreign_key_exists(table, fk_name):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(fk.get('name') == fk_name for fk in insp.get_foreign_keys(table))


def _index_exists(table, index_name):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(index.get('name') == index_name for index in insp.get_indexes(table))


def upgrade():
    # 1. Add status column to user_grammar_topic_status
    if _table_exists('user_grammar_topic_status') and not _column_exists('user_grammar_topic_status', 'status'):
        op.add_column(
            'user_grammar_topic_status',
            sa.Column('status', sa.String(20), nullable=False, server_default='new')
        )

    # Backfill: set 'theory_completed' where theory_completed = True
    if _table_exists('user_grammar_topic_status') and _column_exists('user_grammar_topic_status', 'status'):
        op.execute("""
            UPDATE user_grammar_topic_status
            SET status = 'theory_completed'
            WHERE theory_completed = TRUE
        """)

    # 2. Add grammar_topic_id column to lessons
    if _table_exists('lessons') and not _column_exists('lessons', 'grammar_topic_id'):
        op.add_column(
            'lessons',
            sa.Column('grammar_topic_id', sa.Integer(), nullable=True)
        )

    # Add FK constraint
    if _table_exists('lessons') and _table_exists('grammar_topics') and not _foreign_key_exists('lessons', 'fk_lessons_grammar_topic_id'):
        op.create_foreign_key(
            'fk_lessons_grammar_topic_id',
            'lessons', 'grammar_topics',
            ['grammar_topic_id'], ['id'],
            ondelete='SET NULL'
        )

    # Add index
    if _table_exists('lessons') and not _index_exists('lessons', 'idx_lessons_grammar_topic_id'):
        op.create_index(
            'idx_lessons_grammar_topic_id',
            'lessons',
            ['grammar_topic_id']
        )


def downgrade():
    if _table_exists('lessons') and _index_exists('lessons', 'idx_lessons_grammar_topic_id'):
        op.drop_index('idx_lessons_grammar_topic_id', table_name='lessons')
    if _table_exists('lessons') and _foreign_key_exists('lessons', 'fk_lessons_grammar_topic_id'):
        op.drop_constraint('fk_lessons_grammar_topic_id', 'lessons', type_='foreignkey')
    if _table_exists('lessons') and _column_exists('lessons', 'grammar_topic_id'):
        op.drop_column('lessons', 'grammar_topic_id')
    if _table_exists('user_grammar_topic_status') and _column_exists('user_grammar_topic_status', 'status'):
        op.drop_column('user_grammar_topic_status', 'status')
