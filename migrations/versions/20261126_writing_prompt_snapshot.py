"""Retain the issued writing prompt beside each new bound attempt."""

import sqlalchemy as sa
from alembic import op

revision = '20261126_writing_prompt_snapshot'
down_revision = '20261126_chapter_text_revisions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_writing_attempts', sa.Column('prompt_snapshot', sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    op.drop_column('user_writing_attempts', 'prompt_snapshot')
