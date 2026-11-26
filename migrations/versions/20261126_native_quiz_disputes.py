"""Keep the acceptance receipt for a rejected native quiz check."""

from alembic import op
import sqlalchemy as sa

revision = "20261126_native_quiz_disputes"
down_revision = "20261125_content_moderator"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("answer_dispute_reports", sa.Column(
        "course_web_reported", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column("answer_dispute_reports", sa.Column("course_web_answer", sa.JSON(none_as_null=True)))
    # Before native course reports launched, attributed course reports came from the web.
    op.execute(sa.text("""
        UPDATE answer_dispute_reports SET course_web_reported = true
        WHERE EXISTS (
            SELECT 1 FROM answer_disputes
            WHERE answer_disputes.id = answer_dispute_reports.dispute_id
              AND answer_disputes.lesson_id IS NOT NULL
        )
    """))
    op.create_table(
        "native_course_dispute_receipts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("answer_dispute_reports.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("nonce", sa.String(32), nullable=False),
        sa.Column("input_kind", sa.String(8), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
    )
    op.create_index("ix_native_course_dispute_receipts_report_id", "native_course_dispute_receipts", ["report_id"])


def downgrade() -> None:
    op.drop_table("native_course_dispute_receipts")
    op.drop_column("answer_dispute_reports", "course_web_answer")
    op.drop_column("answer_dispute_reports", "course_web_reported")
