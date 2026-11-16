"""Persist native supplementary practice and its repeat receipts.
Revision ID: 20261116_native_learning_runs
Revises: 20261116_native_srs_state
"""

from alembic import op
import sqlalchemy as sa

revision = "20261116_native_learning_runs"
down_revision = "20261116_native_srs_state"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "native_learning_runs",
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("study_sessions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "request_id", name="uq_native_learning_request"),
    )


def downgrade():
    op.drop_table("native_learning_runs")
