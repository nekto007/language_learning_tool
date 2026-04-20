"""Add feature flag and tables for the linear daily plan.

Adds:
- users.use_linear_plan flag for rolling out the linear daily plan.
- user_reading_preference — tracks selected reading book per user.
- quiz_error_log — stores incorrect quiz answers for error-review slot.
- grammar_theory_view — records when grammar theory is surfaced inside curriculum lessons.

Revision ID: 20260420_add_linear_daily_plan
Revises: 20260418_add_route_step_added_unique_index
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '20260420_add_linear_daily_plan'
down_revision = '20260418_add_route_step_added_unique_index'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column(
            'use_linear_plan',
            sa.Boolean(),
            nullable=False,
            server_default='false',
        ),
    )

    op.create_table(
        'user_reading_preference',
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            'book_id',
            sa.Integer(),
            sa.ForeignKey('book.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'selected_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )
    op.create_index(
        'idx_user_reading_preference_book',
        'user_reading_preference',
        ['book_id'],
    )

    op.create_table(
        'quiz_error_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'lesson_id',
            sa.Integer(),
            sa.ForeignKey('lessons.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'question_payload',
            postgresql.JSONB().with_variant(sa.JSON(), 'sqlite'),
            nullable=False,
        ),
        sa.Column(
            'answered_wrong_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
        sa.Column(
            'resolved_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )
    op.create_index(
        'idx_quiz_error_log_user_resolved',
        'quiz_error_log',
        ['user_id', 'resolved_at'],
    )
    op.create_index(
        'idx_quiz_error_log_user_created',
        'quiz_error_log',
        ['user_id', 'created_at'],
    )

    op.create_table(
        'grammar_theory_view',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('users.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'topic_id',
            sa.Integer(),
            sa.ForeignKey('grammar_topics.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'lesson_id',
            sa.Integer(),
            sa.ForeignKey('lessons.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column(
            'shown_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )
    op.create_index(
        'idx_grammar_theory_view_user_lesson',
        'grammar_theory_view',
        ['user_id', 'lesson_id'],
    )


def downgrade():
    op.drop_index('idx_grammar_theory_view_user_lesson', table_name='grammar_theory_view')
    op.drop_table('grammar_theory_view')

    op.drop_index('idx_quiz_error_log_user_created', table_name='quiz_error_log')
    op.drop_index('idx_quiz_error_log_user_resolved', table_name='quiz_error_log')
    op.drop_table('quiz_error_log')

    op.drop_index('idx_user_reading_preference_book', table_name='user_reading_preference')
    op.drop_table('user_reading_preference')

    op.drop_column('users', 'use_linear_plan')
