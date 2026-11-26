"""Track chapter text changes and cache confirmed reader revisions."""

import sqlalchemy as sa
from alembic import op

revision = '20261126_chapter_text_revisions'
down_revision = '20261126_book_text_policy'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('chapter', sa.Column('text_generation', sa.BigInteger(), nullable=False, server_default='1'))
    op.create_table(
        'chapter_text_revision_cache',
        sa.Column('chapter_id', sa.Integer(), sa.ForeignKey('chapter.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('effective_percent', sa.SmallInteger(), primary_key=True),
        sa.Column('projection', sa.String(6), primary_key=True),
        sa.Column('generation', sa.BigInteger(), nullable=False),
        sa.Column('revision', sa.String(67), nullable=False),
        sa.CheckConstraint('effective_percent BETWEEN 1 AND 100', name='ck_chapter_revision_percent'),
        sa.CheckConstraint("projection IN ('reader', 'admin')", name='ck_chapter_revision_projection'),
    )
    if op.get_context().dialect.name != 'postgresql':
        return
    op.execute("""
        CREATE FUNCTION advance_chapter_text_generation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.text_generation := OLD.text_generation
                + CASE WHEN NEW.text_raw IS DISTINCT FROM OLD.text_raw THEN 1 ELSE 0 END;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER chapter_text_generation
        BEFORE UPDATE OF text_raw, text_generation ON chapter
        FOR EACH ROW EXECUTE FUNCTION advance_chapter_text_generation()
    """)


def downgrade() -> None:
    if op.get_context().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER chapter_text_generation ON chapter')
        op.execute('DROP FUNCTION advance_chapter_text_generation()')
    op.drop_table('chapter_text_revision_cache')
    op.drop_column('chapter', 'text_generation')
