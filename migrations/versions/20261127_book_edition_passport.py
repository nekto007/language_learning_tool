"""Store optional library edition identifiers and source formats."""

import sqlalchemy as sa
from alembic import op

revision = '20261127_book_edition_passport'
down_revision = '20261127_web_writing_submission'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('book', sa.Column('source_edition_id', sa.String(255), nullable=True))
    op.add_column('book', sa.Column('source_format', sa.String(12), nullable=True))


def downgrade() -> None:
    op.drop_column('book', 'source_format')
    op.drop_column('book', 'source_edition_id')
