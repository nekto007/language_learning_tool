"""Add performance indexes for critical queries

Revision ID: 51563928c8a8
Revises: 658ebfd64120
Create Date: 2025-11-20 10:33:10.904069

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '51563928c8a8'
down_revision = '658ebfd64120'
branch_labels = None
depends_on = None


def upgrade():
    # UserWord composite index for bulk status queries (book_words, vocabulary_lesson)
    op.create_index(
        'idx_user_word_user_word_composite',
        'user_words',
        ['user_id', 'word_id'],
        unique=False
    )

    # UserCardDirection composite index for SRS card queries (cards_deck)
    op.create_index(
        'idx_card_direction_review_lookup',
        'user_card_directions',
        ['user_word_id', 'next_review'],
        unique=False
    )

    # QuizDeckWord composite for deck sync operations (sync_master_decks)
    op.create_index(
        'idx_deck_word_deck_word_composite',
        'quiz_deck_words',
        ['deck_id', 'word_id'],
        unique=False
    )

    # Book-word link for book word list queries
    op.create_index(
        'idx_book_word_link_book_word',
        'word_book_link',
        ['book_id', 'word_id'],
        unique=False
    )

    # LessonProgress user+status for dashboard queries
    op.create_index(
        'idx_lesson_progress_user_status_composite',
        'lesson_progress',
        ['user_id', 'status', 'last_activity'],
        unique=False
    )

    # StudySession user+start_time for session tracking
    op.create_index(
        'idx_study_session_user_start_time',
        'study_sessions',
        ['user_id', 'start_time'],
        unique=False
    )

    # QuizResult user+deck+completed for quiz history
    op.create_index(
        'idx_quiz_result_user_deck_completed',
        'quiz_results',
        ['user_id', 'deck_id', 'completed_at'],
        unique=False
    )


def downgrade():
    op.drop_index('idx_quiz_result_user_deck_completed', table_name='quiz_results')
    op.drop_index('idx_study_session_user_start_time', table_name='study_sessions')
    op.drop_index('idx_lesson_progress_user_status_composite', table_name='lesson_progress')
    op.drop_index('idx_book_word_link_book_word', table_name='word_book_link')
    op.drop_index('idx_deck_word_deck_word_composite', table_name='quiz_deck_words')
    op.drop_index('idx_card_direction_review_lookup', table_name='user_card_directions')
    op.drop_index('idx_user_word_user_word_composite', table_name='user_words')
