"""Give each book a durable version of its text access policy."""

import sqlalchemy as sa
from alembic import op

revision = '20261126_book_text_policy'
down_revision = '20261126_native_quiz_disputes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('book', sa.Column('text_policy_revision', sa.BigInteger(), nullable=False, server_default='1'))
    if op.get_context().dialect.name != 'postgresql':
        return
    op.execute("""
        CREATE FUNCTION advance_book_text_policy_revision() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.text_policy_revision := OLD.text_policy_revision;
            IF ROW(NEW.rights_status, NEW.allowed_text_percent, NEW.is_free_access,
                   NEW.is_published, NEW.expiration_date)
               IS DISTINCT FROM
               ROW(OLD.rights_status, OLD.allowed_text_percent, OLD.is_free_access,
                   OLD.is_published, OLD.expiration_date) THEN
                NEW.text_policy_revision := OLD.text_policy_revision + 1;
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER book_text_policy_revision
        BEFORE UPDATE OF rights_status, allowed_text_percent, is_free_access,
                         is_published, expiration_date, text_policy_revision ON book
        FOR EACH ROW EXECUTE FUNCTION advance_book_text_policy_revision()
    """)


def downgrade() -> None:
    if op.get_context().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER book_text_policy_revision ON book')
        op.execute('DROP FUNCTION advance_book_text_policy_revision()')
    op.drop_column('book', 'text_policy_revision')
