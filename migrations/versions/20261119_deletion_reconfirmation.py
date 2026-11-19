"""Bounded account deletion verification and transactional history."""

from alembic import op
import sqlalchemy as sa

revision = "20261119_deletion_reconfirmation"
down_revision = "20261118_account_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "account_deletion_requests",
        sa.Column("requires_reconfirmation", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("account_deletion_requests", sa.Column("reconfirmation_reason", sa.String(1000), nullable=True))
    op.add_column("account_deletion_requests", sa.Column("reconfirmation_requested_at", sa.DateTime(), nullable=True))
    op.add_column("account_deletion_requests", sa.Column("history", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column(
        "account_deletion_mail", sa.Column("purpose", sa.String(24), nullable=False, server_default="completed")
    )


def downgrade():
    op.drop_column("account_deletion_mail", "purpose")
    for name in ["history", "reconfirmation_requested_at", "reconfirmation_reason", "requires_reconfirmation"]:
        op.drop_column("account_deletion_requests", name)
