"""Attribute answer reports and their verified attempts to individual learners."""

import sqlalchemy as sa
from alembic import op

revision = "20261125_answer_dispute_reports"
down_revision = "20261124_grammar_submit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lesson_attempts", sa.Column("submission_nonce", sa.String(32)))
    op.create_table(
        "answer_dispute_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dispute_id", sa.Integer(), sa.ForeignKey("answer_disputes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grammar_attempt_id", sa.Integer(), sa.ForeignKey("grammar_attempts.id", ondelete="SET NULL")),
        sa.Column("course_nonce", sa.String(32)),
        sa.Column("course_correction_id", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("credited_at", sa.DateTime(timezone=True)),
        sa.Column("thanked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("dispute_id", "user_id", name="uq_answer_dispute_report_user"),
    )
    op.create_index("ix_answer_dispute_reports_user_id", "answer_dispute_reports", ["user_id"])


def downgrade() -> None:
    op.drop_table("answer_dispute_reports")
    op.drop_column("lesson_attempts", "submission_nonce")
