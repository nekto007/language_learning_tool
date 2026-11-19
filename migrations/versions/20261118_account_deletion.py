"""Manual account deletion requests, completion mail and durable file cleanup."""
from alembic import op
import sqlalchemy as sa

revision = "20261118_account_deletion"
down_revision = "20261117_mobile_push"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("account_deletion_requests",
        sa.Column("id",sa.String(64),primary_key=True),
        sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="SET NULL"),nullable=True,unique=True),
        sa.Column("status",sa.String(16),nullable=False,server_default="pending"),
        sa.Column("requested_at",sa.DateTime(),nullable=False),
        sa.Column("earliest_deletion_at",sa.DateTime(),nullable=False),
        sa.Column("latest_deletion_at",sa.DateTime(),nullable=False),
        sa.Column("admin_notice_after",sa.DateTime(),nullable=False),
        sa.Column("cancelled_at",sa.DateTime(),nullable=True),
        sa.Column("completed_at",sa.DateTime(),nullable=True),
        sa.Column("reviewed_by",sa.Integer(),sa.ForeignKey("users.id",ondelete="SET NULL"),nullable=True))
    op.create_index("ix_account_deletion_requests_status","account_deletion_requests",["status"])
    op.create_index("ix_account_deletion_requests_latest_deletion_at","account_deletion_requests",["latest_deletion_at"])
    op.create_index("ix_account_deletion_requests_admin_notice_after","account_deletion_requests",["admin_notice_after"])
    op.create_table("account_deletion_mail",
        sa.Column("request_id",sa.String(64),sa.ForeignKey("account_deletion_requests.id",ondelete="CASCADE"),primary_key=True),
        sa.Column("encrypted_email",sa.Text(),nullable=True),
        sa.Column("attempts",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("available_at",sa.DateTime(),nullable=False),
        sa.Column("sent_at",sa.DateTime(),nullable=True))
    op.create_index("ix_account_deletion_mail_available_at","account_deletion_mail",["available_at"])
    op.create_table("account_deletion_files",
        sa.Column("path", sa.String(512), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(), nullable=False))
    op.create_index("ix_account_deletion_files_available_at", "account_deletion_files", ["available_at"])


def downgrade():
    op.drop_index("ix_account_deletion_files_available_at", table_name="account_deletion_files")
    op.drop_table("account_deletion_files")
    op.drop_index("ix_account_deletion_mail_available_at",table_name="account_deletion_mail")
    op.drop_table("account_deletion_mail")
    op.drop_index("ix_account_deletion_requests_admin_notice_after",table_name="account_deletion_requests")
    op.drop_index("ix_account_deletion_requests_latest_deletion_at",table_name="account_deletion_requests")
    op.drop_index("ix_account_deletion_requests_status",table_name="account_deletion_requests")
    op.drop_table("account_deletion_requests")
