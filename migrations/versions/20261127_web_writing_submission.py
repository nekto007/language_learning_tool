"""Keep one atomic receipt beside a browser's identified writing attempt."""

import sqlalchemy as sa
from alembic import op

revision = '20261127_web_writing_submission'
down_revision = '20261127_merge_web_practice'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user_writing_attempts', sa.Column('web_submission_id', sa.String(32), nullable=True))
    op.add_column('user_writing_attempts',
                  sa.Column('web_submission_receipt', sa.JSON(none_as_null=True), nullable=True))
    op.create_unique_constraint('uq_writing_web_submission', 'user_writing_attempts',
                                ['user_id', 'lesson_id', 'web_submission_id'])


def downgrade() -> None:
    op.drop_constraint('uq_writing_web_submission', 'user_writing_attempts', type_='unique')
    op.drop_column('user_writing_attempts', 'web_submission_receipt')
    op.drop_column('user_writing_attempts', 'web_submission_id')
