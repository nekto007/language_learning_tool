"""Bind a themed quiz session to the set it was started for.

``study_sessions`` carried no set reference, so ``_record_word_set_result``
had to trust the slug posted back in the completion body: a run started on
set A could be recorded against any other published set B, corrupting that
set's attempt count, best score and the «what to study next» suggestion.

Nullable by design — every other session type (cards, deck quiz, matching)
leaves it NULL, and sessions opened before this migration stay NULL too.

Revision ID: 20260828_study_session_word_set
Revises: 20260826_drop_personal_association
Create Date: 2026-08-28
"""

import sqlalchemy as sa
from alembic import op

revision = '20260828_study_session_word_set'
down_revision = '20260826_drop_personal_association'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'study_sessions',
        sa.Column('word_set_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_study_sessions_word_set_id',
        'study_sessions',
        'word_sets',
        ['word_set_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade():
    op.drop_constraint(
        'fk_study_sessions_word_set_id', 'study_sessions', type_='foreignkey'
    )
    op.drop_column('study_sessions', 'word_set_id')
