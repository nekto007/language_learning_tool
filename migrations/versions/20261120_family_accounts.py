"""Confirmed family links and single-use, account-bound invitations."""
from alembic import op
import sqlalchemy as sa

revision = "20261120_family_accounts"
down_revision = "20261119_deletion_reconfirmation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "family_links",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("child_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_version", sa.String(128), nullable=False),
        sa.Column("child_version", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("child_id", name="uq_family_links_child_id"),
        sa.CheckConstraint("parent_id <> child_id", name="ck_family_different_users"),
    )
    op.create_index("ix_family_links_parent_id", "family_links", ["parent_id"])
    op.create_table(
        "family_invitations",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("parent_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("child_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_version", sa.String(128), nullable=False),
        sa.Column("child_version", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime()),
    )
    for column in ("parent_id", "child_id"):
        op.create_index("ix_family_invitations_" + column, "family_invitations", [column])


def downgrade():
    op.drop_table("family_invitations")
    op.drop_table("family_links")
