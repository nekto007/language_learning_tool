"""Native email proofs, durable mail and social account identities."""

from alembic import op
import sqlalchemy as sa

revision = "20261117_mobile_auth"
down_revision = "20261117_reader_vocabulary"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mobile_auth_challenges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("email", sa.String(120)),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("code_hash", sa.String(64)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime()),
    )
    op.create_index(
        "ix_mobile_auth_challenges_email", "mobile_auth_challenges", ["email"]
    )
    op.create_index(
        "ix_mobile_auth_challenges_expires_at", "mobile_auth_challenges", ["expires_at"]
    )
    op.create_table(
        "mobile_auth_throttles",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("window_at", sa.DateTime(), nullable=False),
        sa.Column("last_at", sa.DateTime(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "mobile_auth_mail",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "challenge_id",
            sa.String(64),
            sa.ForeignKey("mobile_auth_challenges.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("email", sa.String(120), nullable=False),
        sa.Column("encrypted_code", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("locked_at", sa.DateTime()),
    )
    op.create_index("ix_mobile_auth_mail_status", "mobile_auth_mail", ["status"])
    op.create_table(
        "social_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("encrypted_refresh", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "subject", name="uq_social_provider_subject"),
    )
    op.create_index("ix_social_identities_user_id", "social_identities", ["user_id"])


def downgrade():
    op.drop_table("social_identities")
    op.drop_table("mobile_auth_mail")
    op.drop_table("mobile_auth_throttles")
    op.drop_table("mobile_auth_challenges")
