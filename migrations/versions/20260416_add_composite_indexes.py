"""Add composite DB indexes for high-traffic queries

study_sessions lacks any index on user_id despite being filtered heavily by user+time.
quiz_results needs user_id-first index for count queries.
lesson_attempts needs (user_id, started_at) for insights date-range queries.

Revision ID: 20260416_add_composite_indexes
Revises: add_password_reset_tokens
Create Date: 2026-04-16
"""
from alembic import op


revision = '20260416_add_composite_indexes'
down_revision = 'add_password_reset_tokens'
branch_labels = None
depends_on = None


def upgrade():
    # study_sessions: no indexes existed; add user_id and composite with start_time
    op.create_index(
        'idx_study_sessions_user_id',
        'study_sessions',
        ['user_id'],
    )
    op.create_index(
        'idx_study_sessions_user_start_time',
        'study_sessions',
        ['user_id', 'start_time'],
    )

    # quiz_results: existing index is (deck_id, user_id); add user_id-first for count queries
    op.create_index(
        'idx_quiz_results_user_id',
        'quiz_results',
        ['user_id'],
    )
    op.create_index(
        'idx_quiz_results_user_completed_at',
        'quiz_results',
        ['user_id', 'completed_at'],
    )

    # lesson_attempts: add (user_id, started_at) for insights_service date-range queries
    op.create_index(
        'idx_lesson_attempts_user_started_at',
        'lesson_attempts',
        ['user_id', 'started_at'],
    )


def downgrade():
    op.drop_index('idx_lesson_attempts_user_started_at', table_name='lesson_attempts')
    op.drop_index('idx_quiz_results_user_completed_at', table_name='quiz_results')
    op.drop_index('idx_quiz_results_user_id', table_name='quiz_results')
    op.drop_index('idx_study_sessions_user_start_time', table_name='study_sessions')
    op.drop_index('idx_study_sessions_user_id', table_name='study_sessions')
