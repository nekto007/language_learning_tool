"""Add curated themed word sets and their quiz results.

A WordSet is the editorially controlled group a learner browses and quizzes
(«Цвета», «Одежда»). It deliberately does not reuse `topics`: that table is an
open, machine-populated space where the overwhelming majority of rows hold a
single word, so it can carry vocabulary but cannot be shown as a catalogue.

Revision ID: 20260815_word_sets
Revises: 20260808_clear_null_literal_word_lists
Create Date: 2026-08-15
"""

from alembic import op
import sqlalchemy as sa


revision = '20260815_word_sets'
down_revision = '20260808_clear_null_literal_word_lists'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'word_sets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('icon', sa.String(length=8), nullable=True),
        # Accent is a palette NAME ('indigo', 'amber', ...), never a hex value:
        # the template maps it to a CSS class, so no colour is ever printed
        # into a style="..." attribute.
        sa.Column('accent', sa.String(length=20), nullable=False, server_default='indigo'),
        sa.Column('level', sa.String(length=10), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', name='uq_word_sets_slug'),
    )
    op.create_index('ix_word_sets_slug', 'word_sets', ['slug'])
    op.create_index('idx_word_set_published_order', 'word_sets', ['is_published', 'sort_order'])

    op.create_table(
        'word_set_words',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('set_id', sa.Integer(), nullable=False),
        sa.Column('word_id', sa.Integer(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.ForeignKeyConstraint(['set_id'], ['word_sets.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['word_id'], ['collection_words.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('set_id', 'word_id', name='uix_word_set_word'),
    )
    op.create_index('idx_word_set_word_set', 'word_set_words', ['set_id'])
    op.create_index('idx_word_set_word_word', 'word_set_words', ['word_id'])

    op.create_table(
        'word_set_quiz_results',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('set_id', sa.Integer(), nullable=False),
        sa.Column('total_questions', sa.Integer(), nullable=False),
        sa.Column('correct_answers', sa.Integer(), nullable=False),
        sa.Column('score_percentage', sa.Float(), nullable=False),
        sa.Column('time_taken', sa.Integer(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['set_id'], ['word_sets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_word_set_quiz_results_completed_at', 'word_set_quiz_results', ['completed_at'])
    op.create_index('idx_word_set_result_user_set', 'word_set_quiz_results', ['user_id', 'set_id'])
    op.create_index(
        'idx_word_set_result_user_completed', 'word_set_quiz_results', ['user_id', 'completed_at']
    )


def downgrade():
    op.drop_index('idx_word_set_result_user_completed', table_name='word_set_quiz_results')
    op.drop_index('idx_word_set_result_user_set', table_name='word_set_quiz_results')
    op.drop_index('ix_word_set_quiz_results_completed_at', table_name='word_set_quiz_results')
    op.drop_table('word_set_quiz_results')

    op.drop_index('idx_word_set_word_word', table_name='word_set_words')
    op.drop_index('idx_word_set_word_set', table_name='word_set_words')
    op.drop_table('word_set_words')

    op.drop_index('idx_word_set_published_order', table_name='word_sets')
    op.drop_index('ix_word_sets_slug', table_name='word_sets')
    op.drop_table('word_sets')
