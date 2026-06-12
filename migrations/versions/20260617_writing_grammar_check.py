"""Add LanguageTool grammar check columns to user_writing_attempts.

Revision ID: 20260617_writing_grammar_check
Revises: 20260616_profile_is_public
Create Date: 2026-06-17

grammar_error_count: NULL = проверка не выполнялась, 0 = проверено и чисто.
grammar_matches: упрощённый список match'ей LanguageTool
(offset/length/message/replacements/category) для подсветки в истории.
"""

from alembic import op
import sqlalchemy as sa


revision = '20260617_writing_grammar_check'
down_revision = '20260616_profile_is_public'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'user_writing_attempts',
        sa.Column('grammar_error_count', sa.Integer(), nullable=True),
    )
    op.add_column(
        'user_writing_attempts',
        sa.Column('grammar_matches', sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column('user_writing_attempts', 'grammar_matches')
    op.drop_column('user_writing_attempts', 'grammar_error_count')
