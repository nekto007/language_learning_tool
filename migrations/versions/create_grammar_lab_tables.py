"""Create Grammar Lab tables

Revision ID: create_grammar_lab_tables
Revises:
Create Date: 2024-12-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'create_grammar_lab_tables'
down_revision = None  # Will be set by alembic
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name):
    return table_name in _inspector().get_table_names()


def _index_exists(table_name, index_name):
    return any(index.get('name') == index_name for index in _inspector().get_indexes(table_name))


def _unique_constraint_exists(table_name, constraint_name):
    return any(
        constraint.get('name') == constraint_name
        for constraint in _inspector().get_unique_constraints(table_name)
    )


def upgrade():
    # Some production environments already have part of Grammar Lab schema from
    # older migration branches. Keep this migration idempotent so Alembic can
    # traverse the historical branch graph without crashing on duplicate DDL.
    if not _table_exists('grammar_topics'):
        op.create_table(
            'grammar_topics',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('slug', sa.String(100), unique=True, nullable=False),
            sa.Column('title', sa.String(200), nullable=False),
            sa.Column('title_ru', sa.String(200), nullable=False),
            sa.Column('level', sa.String(10), nullable=False),
            sa.Column('order', sa.Integer(), default=0),
            sa.Column('content', JSONB, nullable=False, server_default='{}'),
            sa.Column('estimated_time', sa.Integer(), default=15),
            sa.Column('difficulty', sa.Integer(), default=1),
            sa.Column('created_at', sa.DateTime(timezone=True)),
            sa.Column('updated_at', sa.DateTime(timezone=True)),
        )

    # Create indexes for grammar_topics
    if not _index_exists('grammar_topics', 'idx_grammar_topics_level'):
        op.create_index('idx_grammar_topics_level', 'grammar_topics', ['level'])
    if not _index_exists('grammar_topics', 'idx_grammar_topics_slug'):
        op.create_index('idx_grammar_topics_slug', 'grammar_topics', ['slug'])

    if not _table_exists('grammar_exercises'):
        op.create_table(
            'grammar_exercises',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('topic_id', sa.Integer(), sa.ForeignKey('grammar_topics.id', ondelete='CASCADE'), nullable=False),
            sa.Column('exercise_type', sa.String(50), nullable=False),
            sa.Column('content', JSONB, nullable=False),
            sa.Column('difficulty', sa.Integer(), default=1),
            sa.Column('order', sa.Integer(), default=0),
            sa.Column('created_at', sa.DateTime(timezone=True)),
        )

    # Create index for grammar_exercises
    if not _index_exists('grammar_exercises', 'idx_grammar_exercises_topic'):
        op.create_index('idx_grammar_exercises_topic', 'grammar_exercises', ['topic_id'])

    if not _table_exists('user_grammar_progress'):
        op.create_table(
            'user_grammar_progress',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('topic_id', sa.Integer(), sa.ForeignKey('grammar_topics.id', ondelete='CASCADE'), nullable=False),
            sa.Column('theory_completed', sa.Boolean(), default=False),
            sa.Column('theory_completed_at', sa.DateTime(timezone=True)),
            sa.Column('mastery_level', sa.Integer(), default=0),
            sa.Column('correct_streak', sa.Integer(), default=0),
            sa.Column('total_attempts', sa.Integer(), default=0),
            sa.Column('correct_attempts', sa.Integer(), default=0),
            sa.Column('ease_factor', sa.Float(), default=2.5),
            sa.Column('interval', sa.Integer(), default=0),
            sa.Column('next_review', sa.DateTime(timezone=True)),
            sa.Column('last_reviewed', sa.DateTime(timezone=True)),
            sa.Column('error_stats', JSONB, server_default='{}'),
            sa.Column('xp_earned', sa.Integer(), default=0),
            sa.Column('time_spent', sa.Integer(), default=0),
            sa.Column('created_at', sa.DateTime(timezone=True)),
            sa.Column('updated_at', sa.DateTime(timezone=True)),
        )

    # Create unique constraint and indexes for user_grammar_progress
    if not _unique_constraint_exists('user_grammar_progress', 'uq_user_grammar_topic'):
        op.create_unique_constraint('uq_user_grammar_topic', 'user_grammar_progress', ['user_id', 'topic_id'])
    if not _index_exists('user_grammar_progress', 'idx_user_grammar_progress_user'):
        op.create_index('idx_user_grammar_progress_user', 'user_grammar_progress', ['user_id'])
    if not _index_exists('user_grammar_progress', 'idx_user_grammar_progress_next_review'):
        op.create_index('idx_user_grammar_progress_next_review', 'user_grammar_progress', ['user_id', 'next_review'])

    if not _table_exists('grammar_attempts'):
        op.create_table(
            'grammar_attempts',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('exercise_id', sa.Integer(), sa.ForeignKey('grammar_exercises.id', ondelete='CASCADE'), nullable=False),
            sa.Column('is_correct', sa.Boolean(), nullable=False),
            sa.Column('user_answer', sa.Text()),
            sa.Column('time_spent', sa.Integer()),
            sa.Column('session_id', sa.String(100)),
            sa.Column('source', sa.String(50)),
            sa.Column('created_at', sa.DateTime(timezone=True)),
        )

    # Create indexes for grammar_attempts
    if not _index_exists('grammar_attempts', 'idx_grammar_attempts_user'):
        op.create_index('idx_grammar_attempts_user', 'grammar_attempts', ['user_id'])
    if not _index_exists('grammar_attempts', 'idx_grammar_attempts_exercise'):
        op.create_index('idx_grammar_attempts_exercise', 'grammar_attempts', ['exercise_id'])
    if not _index_exists('grammar_attempts', 'idx_grammar_attempts_session'):
        op.create_index('idx_grammar_attempts_session', 'grammar_attempts', ['session_id'])


def downgrade():
    # Drop tables in reverse order
    if _table_exists('grammar_attempts'):
        op.drop_table('grammar_attempts')
    if _table_exists('user_grammar_progress'):
        op.drop_table('user_grammar_progress')
    if _table_exists('grammar_exercises'):
        op.drop_table('grammar_exercises')
    if _table_exists('grammar_topics'):
        op.drop_table('grammar_topics')
