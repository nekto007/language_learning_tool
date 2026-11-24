"""Optional idempotency receipts on Grammar Lab attempts."""
import sqlalchemy as sa
from alembic import op

revision = '20261124_grammar_submit'
down_revision = '20261124_lab_disputes'
branch_labels = None
depends_on = None

TABLE = 'grammar_attempts'
INDEX = 'uq_grammar_attempts_user_submission'
PARTIAL = sa.text('submission_id IS NOT NULL')


def upgrade() -> None:
    context = op.get_context()
    if context.dialect.name == 'postgresql':
        # Nullable columns without defaults avoid rewriting the attempts table.
        # The concurrent index runs after a commit, so allow a retry if it fails.
        op.execute('ALTER TABLE grammar_attempts ADD COLUMN IF NOT EXISTS submission_id UUID, '
                   'ADD COLUMN IF NOT EXISTS submission_receipt JSONB')
        with context.autocommit_block():
            valid = None if context.as_sql else op.get_bind().execute(sa.text(
                "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass("
                "'uq_grammar_attempts_user_submission')"
            )).scalar()
            if valid is False:
                op.drop_index(INDEX, table_name=TABLE, postgresql_concurrently=True)
            if valid is not True:
                op.create_index(INDEX, TABLE, ['user_id', 'submission_id'], unique=True,
                                postgresql_where=PARTIAL, postgresql_concurrently=True)
        return

    op.add_column(TABLE, sa.Column('submission_id', sa.String(36), nullable=True))
    op.add_column(TABLE, sa.Column('submission_receipt', sa.JSON(), nullable=True))
    op.create_index(INDEX, TABLE, ['user_id', 'submission_id'], unique=True, sqlite_where=PARTIAL)


def downgrade() -> None:
    context = op.get_context()
    if context.dialect.name == 'postgresql':
        with context.autocommit_block():
            op.execute('DROP INDEX CONCURRENTLY IF EXISTS uq_grammar_attempts_user_submission')
        op.execute('ALTER TABLE grammar_attempts DROP COLUMN IF EXISTS submission_receipt, '
                   'DROP COLUMN IF EXISTS submission_id')
        return

    op.drop_index(INDEX, table_name=TABLE)
    op.drop_column(TABLE, 'submission_receipt')
    op.drop_column(TABLE, 'submission_id')
