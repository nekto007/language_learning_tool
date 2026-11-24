"""Give an explicitly appointed moderator access to content editing."""
import sqlalchemy as sa
from alembic import op

revision = "20261125_content_moderator"
down_revision = "20261125_answer_dispute_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_moderator', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column('users', 'is_moderator')
