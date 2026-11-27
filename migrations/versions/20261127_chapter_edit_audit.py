"""Record version metadata for future chapter edits."""

import sqlalchemy as sa
from alembic import op

revision = '20261127_chapter_edit_audit'
down_revision = '20261127_book_edition_passport'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'admin_chapter_edit_audit',
        sa.Column('audit_id', sa.Integer(), sa.ForeignKey('admin_audit_log.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('chapter_number', sa.Integer(), nullable=False),
        sa.Column('chapter_title', sa.String(255), nullable=False),
        sa.Column('revision_before', sa.String(64), nullable=False),
        sa.Column('revision_after', sa.String(64), nullable=False),
        sa.Column('generation_before', sa.BigInteger(), nullable=False),
        sa.Column('generation_after', sa.BigInteger(), nullable=False),
        sa.Column('paragraph', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('admin_chapter_edit_audit')
